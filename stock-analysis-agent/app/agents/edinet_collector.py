"""EDINET 書類取得 collector (proposal 0006 Phase 1d)。

orchestrator から呼ばれ、 指定 ticker (証券コード or `XXXX.T`) に対応する
**最新有価証券報告書 + 直近 N 期の四半期報告書** を EDINET API で取得する。

返り値は書類メタデータ + 書類本体 (PDF) のリスト。 Claude Agent SDK 側で
workspace に書き出し、 Read tool で読ませて分析に投入する想定 (orchestrator
側で `Read` ツール経由でローカル PDF を渡す)。

設計判断:
- 失敗時 (API key 無効 / ticker 未登録 / 書類なし) は **空 list を返す**
  (例外で orchestrator 全体を落とさない)。 EDINET は補助情報なので、 取れな
  ければ既存の yfinance + Brave Search で分析を続行する
- `settings.edinet_enabled = false` のとき早期 return → 0 書類
- `code_resolver` (Edinetcode.csv) 未設定なら early-return + warning log
- 探索範囲は直近 `edinet_search_window_days` 日 (default 400 日)。 1 年強で
  年次 + 4 四半期分が捕捉できる
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
)

from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdinetFilingResult:
    """`collect_filings()` の戻り値。 metadata + 本体 PDF のペア。"""

    metadata: DocumentMetadata
    body: DocumentBody


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

    cache = _build_cache()
    async with EdinetClient(
        api_key=settings.edinet_api_key,
        cache=cache,
        code_resolver=resolver,
        min_interval_sec=settings.edinet_min_interval_sec,
    ) as client:
        # 1) 探索窓内の文書 INDEX を 1 日ずつ取得
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

        # 2) 必要な書類だけ選別: 直近の年次 + 直近 N 期の四半期
        selected = _select_target_filings(
            candidates, n_quarters=settings.edinet_quarterly_lookback
        )
        if not selected:
            return []

        # 3) 本体 (PDF) を取得 (cache 経由)
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
            results.append(EdinetFilingResult(metadata=meta, body=body))

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
