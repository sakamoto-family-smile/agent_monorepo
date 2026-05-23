"""EDINET 書類取得 collector (proposal 0006 Phase 1d + Phase 1e)。

orchestrator から呼ばれ、 指定 ticker (証券コード or `XXXX.T`) に対応する
**最新有価証券報告書 + 直近 N 期の四半期報告書** を取得する。

Phase 1e 以降の取得経路:
1. `code_resolver` で ticker → EDINET code 解決
2. `EdinetIndexRepo.list_by_edinet_code()` で **DB から該当書類を即時 lookup**
3. DB hit → 該当 doc_id だけ EDINET API で本体 (PDF) を取得
4. DB miss (= daily batch が回っていない / 新規銘柄) → Phase 1d の API 全件
   fetch にフォールバック (互換性維持、 ただし latency 高)

設計判断:
- 失敗時 (API key 無効 / ticker 未登録 / 書類なし) は **空 list を返す**
  (例外で orchestrator 全体を落とさない)
- `settings.edinet_enabled = false` のとき早期 return → 0 書類
- DB に該当書類がある場合は 1 日 1 リクエストの 400 回 fetch を **完全 skip**
  (初回 latency ~7 分 → ~10 秒程度に短縮)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from edinet_client import (
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    EdinetClient,
    EdinetCodeResolver,
    GcsCache,
    LocalCache,
    XbrlFinancials,
    parse_xbrl_zip,
)

from config import settings
from services.edinet_index_repo import EdinetIndexRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdinetFilingResult:
    """`collect_filings()` の戻り値。

    - `metadata`: 書類メタデータ (DocumentType / submit_date / 期末 等)
    - `body`: 本体 PDF (Claude が Read tool で読む)
    - `financials`: XBRL から抽出した Tier 1+2 構造化数値 (Phase 2b 以降)。
       XBRL が無い書類 / parse 失敗 / `edinet_enable_xbrl=false` のときは None
    """

    metadata: DocumentMetadata
    body: DocumentBody
    financials: XbrlFinancials | None = None


async def collect_filings(ticker: str) -> list[EdinetFilingResult]:
    """指定 ticker の最新有価証券報告書 + 直近 N 期の四半期報告書を取得する。

    設定で EDINET が無効、 もしくは資料が見つからない場合は **空 list** を返す
    (caller は EDINET なしで分析を続行できる)。

    Args:
        ticker: yfinance 形式の ticker (`7203` / `7203.T` / `285A.T` 等)。

    Returns:
        書類メタデータと PDF 本体のペア list。 古い順 → 新しい順にソート。
    """
    if not settings.edinet_enabled:
        logger.debug("EDINET disabled (settings.edinet_enabled=false), skipping")
        return []
    if not settings.edinet_api_key:
        logger.warning("EDINET_API_KEY not set, skipping EDINET collection")
        return []

    resolver = _build_resolver()
    if resolver is None:
        return []

    edinet_code = resolver.resolve_edinet_code(ticker)
    if not edinet_code:
        logger.info(
            "EDINET code not found for ticker=%s (likely non-listed or US stock)",
            ticker,
        )
        return []

    # 1) DB から事前 INDEX を lookup (Phase 1e の高速経路)
    selected = await _select_filings_from_db(
        edinet_code=edinet_code,
        n_quarters=settings.edinet_quarterly_lookback,
    )

    cache = _build_cache()
    async with EdinetClient(
        api_key=settings.edinet_api_key,
        cache=cache,
        code_resolver=resolver,
        min_interval_sec=settings.edinet_min_interval_sec,
    ) as client:
        # 2) DB miss → 旧経路 (1 日ずつ fetch) にフォールバック
        if not selected:
            logger.info(
                "EDINET index empty in DB for edinet_code=%s, "
                "falling back to direct API fetch (slow). "
                "Run `python -m app.batch.edinet_index_etl` to populate DB.",
                edinet_code,
            )
            candidates = await _gather_filings_for_edinet_code(
                client=client,
                edinet_code=edinet_code,
                window_days=settings.edinet_search_window_days,
            )
            if not candidates:
                logger.info(
                    "no EDINET filings found in window for edinet_code=%s ticker=%s",
                    edinet_code,
                    ticker,
                )
                return []
            selected = _select_target_filings(
                candidates, n_quarters=settings.edinet_quarterly_lookback
            )
        if not selected:
            return []

        # 3) 本体 (PDF + 任意で XBRL) を取得 (cache 経由)
        results: list[EdinetFilingResult] = []
        for meta in selected:
            try:
                body = await client.download(meta.document_id, content_type="pdf")
            except Exception:  # noqa: BLE001 — 1 件失敗で全体を落とさない
                logger.exception(
                    "failed to download EDINET document_id=%s for ticker=%s",
                    meta.document_id,
                    ticker,
                )
                continue
            financials = await _fetch_and_parse_xbrl(client=client, meta=meta)
            results.append(
                EdinetFilingResult(metadata=meta, body=body, financials=financials)
            )

    # 提出日 昇順 (古→新) で返す
    results.sort(key=lambda r: r.metadata.submit_date)
    logger.info(
        "EDINET collected %d filings for ticker=%s (edinet_code=%s)",
        len(results),
        ticker,
        edinet_code,
    )
    return results


def _build_resolver() -> EdinetCodeResolver | None:
    """ticker → EDINET code resolver を構築する。 CSV 未設定なら None。"""
    csv_path = settings.edinet_code_csv_path
    if not csv_path or not Path(csv_path).exists():
        logger.warning(
            "EDINET_CODE_CSV_PATH not configured or missing (path=%r), "
            "EDINET collection will be skipped",
            csv_path,
        )
        return None
    return EdinetCodeResolver.from_csv_path(csv_path)


def _build_cache() -> LocalCache | GcsCache:
    """settings に応じて cache backend を選択。"""
    backend = settings.edinet_cache_backend
    if backend == "gcs":
        if not settings.edinet_cache_gcs_bucket:
            logger.warning(
                "EDINET_CACHE_BACKEND=gcs だが EDINET_CACHE_GCS_BUCKET が未設定。 "
                "LocalCache に fallback"
            )
            return LocalCache(root=settings.edinet_cache_root)
        return GcsCache(
            bucket=settings.edinet_cache_gcs_bucket,
            prefix=settings.edinet_cache_gcs_prefix,
        )
    return LocalCache(root=settings.edinet_cache_root)


async def _gather_filings_for_edinet_code(
    *,
    client: EdinetClient,
    edinet_code: str,
    window_days: int,
) -> list[DocumentMetadata]:
    """過去 window_days 日分の INDEX を fetch して指定 edinet_code の書類のみ返す。

    EDINET API は 1 日 1 リクエスト単位なので、 window_days 回 API を叩く。
    polite rate (1 req/s) を守るため `EdinetClient` 内で間隔調整される。

    400 日 fetch すると 400 リクエスト = 約 7 分程度の API 叩きが発生する。
    将来は Cloud SQL `edinet_documents` の事前 INDEX を引いて当該ロジックを
    skip する (Phase 1e)。
    """
    today = date.today()
    matches: list[DocumentMetadata] = []
    for offset in range(window_days):
        target = today - timedelta(days=offset)
        try:
            docs = await client.list_documents(target)
        except Exception:  # noqa: BLE001
            logger.exception(
                "EDINET list_documents failed for date=%s (continuing)", target
            )
            continue
        for d in docs:
            if d.edinet_code == edinet_code and d.is_available:
                matches.append(d)
    return matches


async def _fetch_and_parse_xbrl(
    *, client: EdinetClient, meta: DocumentMetadata
) -> XbrlFinancials | None:
    """XBRL zip を取得して Tier 1+2 数値を抽出する (proposal 0006 Phase 2b)。

    XBRL を持たない書類 (xbrl_flag=False) や、 機能 off (`edinet_enable_xbrl=false`)
    の場合は None を返して PDF 経路だけで進む。 1 件失敗で全体を落とさない。
    """
    if not settings.edinet_enable_xbrl:
        return None
    if not meta.xbrl_flag:
        logger.debug(
            "no XBRL available for document_id=%s (xbrl_flag=False)",
            meta.document_id,
        )
        return None
    try:
        body = await client.download(meta.document_id, content_type="xbrl_zip")
    except Exception:  # noqa: BLE001
        logger.exception(
            "failed to download XBRL for document_id=%s (PDF only)", meta.document_id
        )
        return None
    try:
        financials = parse_xbrl_zip(body.bytes_payload, document_id=meta.document_id)
    except ImportError:
        # [xbrl] extras が未導入の環境 (e.g., 軽量 deploy)。 警告のみで継続。
        logger.warning(
            "edinet-client[xbrl] extras not installed; "
            "skipping XBRL parsing for document_id=%s. "
            "Set EDINET_ENABLE_XBRL=false to suppress this warning",
            meta.document_id,
        )
        return None
    except Exception:  # noqa: BLE001 — XBRL parser の予期せぬ失敗を吸収
        logger.exception(
            "XBRL parsing failed for document_id=%s (continuing with PDF only)",
            meta.document_id,
        )
        return None
    if not financials.has_tier1_data:
        logger.warning(
            "XBRL parse returned no Tier 1 data for document_id=%s; "
            "concept name mismatch likely. Continuing with PDF only.",
            meta.document_id,
        )
        return None
    logger.info(
        "XBRL parsed for document_id=%s: net_sales=%s, operating_profit=%s, segments=%d",
        meta.document_id,
        financials.net_sales,
        financials.operating_profit,
        len(financials.segments),
    )
    return financials


async def _select_filings_from_db(
    *, edinet_code: str, n_quarters: int
) -> list[DocumentMetadata]:
    """DB (`edinet_documents`) から最新有報 + 直近 N 期の四半期を引く。

    DB が空 (daily batch 未実行) なら空 list を返す → caller は API fallback。
    """
    repo = EdinetIndexRepo()
    try:
        annual_rows = await repo.list_by_edinet_code(
            edinet_code,
            document_types=[DocumentType.ANNUAL_REPORT.value],
            limit=1,
        )
        quarterly_rows = await repo.list_by_edinet_code(
            edinet_code,
            document_types=[DocumentType.QUARTERLY_REPORT.value],
            limit=n_quarters,
        )
    except Exception:  # noqa: BLE001 — テーブル未作成等は warn して fallback へ
        logger.warning(
            "EDINET index DB lookup failed for edinet_code=%s "
            "(table may be missing). Run "
            "`python -m app.batch.edinet_index_etl` to populate. "
            "Falling back to direct API fetch.",
            edinet_code,
        )
        return []
    metas: list[DocumentMetadata] = []
    if annual_rows:
        metas.append(annual_rows[0].to_metadata())
    metas.extend(r.to_metadata() for r in quarterly_rows)
    return metas


def _select_target_filings(
    candidates: list[DocumentMetadata], *, n_quarters: int
) -> list[DocumentMetadata]:
    """候補書類から「最新有報 1 件 + 直近 N 期の四半期 」を選別。"""
    # 提出日 降順
    sorted_docs = sorted(candidates, key=lambda d: d.submit_date, reverse=True)

    annual: DocumentMetadata | None = None
    quarterlies: list[DocumentMetadata] = []
    for d in sorted_docs:
        if d.document_type == DocumentType.ANNUAL_REPORT and annual is None:
            annual = d
        elif d.document_type == DocumentType.QUARTERLY_REPORT and len(quarterlies) < n_quarters:
            quarterlies.append(d)
        if annual is not None and len(quarterlies) >= n_quarters:
            break

    selected: list[DocumentMetadata] = []
    if annual is not None:
        selected.append(annual)
    selected.extend(quarterlies)
    return selected


__all__ = ["EdinetFilingResult", "collect_filings"]
