"""EDINET XBRL parser (proposal 0006 Phase 2a)。

EDINET の有報・四半期報告書 XBRL zip から **構造化財務数値 (Tier 1+2)** を抽出する。

抽出スコープ (Tier 1+2):
- 連結損益: 売上高 / 営業利益 / 経常利益 / 当期純利益
- 連結 BS: 総資産 / 純資産
- セグメント情報: セグメント名・売上高・(可能なら) 営業利益

設計判断:
- Arelle (公式 XBRL processor) を使用。 lazy import で `[xbrl]` extras 未導入時の
  ImportError は明示的にハンドル
- EDINET の concept QName は taxonomy 改訂で揺れるので **複数候補を順次試す**
- 連結優先 (NonConsolidatedMember context は無視)。 連結値が無い純粋単体企業は
  単体値で fallback
- 単位は taxonomy 上は **円** (decimals=-6 で百万円表示) 想定。 normalize して
  すべて 円単位 float で返す
- context の dimensional axis でセグメント別に分離する
- 失敗時 (XBRL 無効 / 主要 concept 不在) は対応フィールドを None で返す。
  caller は PDF fallback などを検討
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ── 抽出対象 concept QName 候補 (優先度順、 上が EDINET 公式 taxonomy 標準) ──
# concept は localname のみで比較する (namespace は jpcrp_cor / jppfs_cor 等で揺れる)
# IFRS suffix 付き concept は IFRS / US-GAAP 採用企業 (例: キオクシア / トヨタ) 対応
_CONCEPT_CANDIDATES: dict[str, tuple[str, ...]] = {
    # 売上高 / 売上収益 / 営業収益
    "net_sales": (
        "NetSales",
        "Revenue",
        "RevenueIFRS",
        "OperatingRevenue1",
        "OperatingRevenue",
        "NetSalesSummaryOfBusinessResults",
        "RevenueIFRSSummaryOfBusinessResults",
    ),
    # 営業利益
    "operating_profit": (
        "OperatingIncome",
        "OperatingProfitLoss",
        "OperatingProfitLossIFRS",
        "OperatingIncomeSummaryOfBusinessResults",
        "OperatingProfitLossIFRSSummaryOfBusinessResults",
    ),
    # 経常利益 (IFRS / US-GAAP 採用企業は欠落することがある)
    "ordinary_profit": (
        "OrdinaryIncome",
        "OrdinaryIncomeLossSummaryOfBusinessResults",
    ),
    # 親会社株主に帰属する当期純利益
    "net_profit": (
        "ProfitLossAttributableToOwnersOfParentIFRS",
        "ProfitLossAttributableToOwnersOfParent",
        "ProfitLossIFRS",
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
    ),
    # 総資産
    "total_assets": (
        "AssetsIFRS",
        "Assets",
        "TotalAssetsSummaryOfBusinessResults",
        "AssetsIFRSSummaryOfBusinessResults",
    ),
    # 純資産 / 自己資本
    "net_assets": (
        "EquityAttributableToOwnersOfParentIFRS",
        "EquityIFRS",
        "NetAssets",
        "Equity",
        "EquityAttributableToOwnersOfParent",
        "NetAssetsSummaryOfBusinessResults",
        "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
    ),
}

# セグメント情報の concept (sales / op profit)
# `RevenuesFromExternalCustomers` は EDINET の標準 (jpcrp_cor)、 多くの J-GAAP 企業が使う
_SEGMENT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "net_sales": (
        "NetSalesOfReportableSegments",
        "RevenuesFromExternalCustomers",
        "RevenueFromExternalCustomers",
        "NetSales",
        "Revenue",
    ),
    "operating_profit": (
        "OperatingIncomeLossOfReportableSegments",
        "SegmentProfitLoss",
        "OperatingIncome",
    ),
}

# セグメント情報を表す軸 (EDINET の各 taxonomy で揺れる)
_SEGMENT_AXIS_KEYWORDS: tuple[str, ...] = (
    "OperatingSegmentsAxis",
    "ReportableSegmentsAxis",
    "BusinessSegmentsAxis",
)

# セグメント member の合計 / 調整 / 除外行 (Tier 2 表からは除外する)
_SEGMENT_MEMBER_EXCLUDES: tuple[str, ...] = (
    "ReportableSegmentsMember",          # 全 reportable 合計
    "TotalOfReportableSegmentsAndOthersMember",  # その他含む合計
    "EliminationsOrAdjustmentsMember",   # 連結調整
    "ReconcilingItemsMember",            # 調整額
    "OperatingSegmentsNotIncludedInReportableSegmentsAndOtherRevenueGeneratingBusinessActivitiesMember",  # 「その他」
)

# セグメント member 名の suffix (削って読みやすい名前にする、 長い順に試す)
_SEGMENT_MEMBER_SUFFIXES: tuple[str, ...] = (
    "ReportableSegmentsMember",
    "Member",
)


class XbrlSegment(BaseModel):
    """セグメント情報 1 件分。"""

    model_config = ConfigDict(frozen=True)

    segment_name: str
    net_sales: float | None = None
    operating_profit: float | None = None


class XbrlFinancials(BaseModel):
    """XBRL から抽出した Tier 1+2 数値の集約。

    数値は **円単位 float** に normalize 済み (taxonomy decimals は内部で処理)。
    値が見つからなかった項目は `None` (= caller は PDF fallback を検討する)。
    """

    model_config = ConfigDict(frozen=True)

    # ── 期間メタデータ ──
    fiscal_year_end: date | None = None              # 会計期間終了日
    period_type: Literal["annual", "quarterly", "semi", "other"] = "other"
    is_consolidated: bool = True

    # ── 連結 P/L (Tier 1) ──
    net_sales: float | None = None
    operating_profit: float | None = None
    ordinary_profit: float | None = None
    net_profit: float | None = None

    # ── 連結 BS (Tier 1) ──
    total_assets: float | None = None
    net_assets: float | None = None

    # ── セグメント情報 (Tier 2) ──
    segments: tuple[XbrlSegment, ...] = Field(default_factory=tuple)

    # ── debug / 監査用 ──
    raw_concept_hits: dict[str, str] = Field(default_factory=dict)  # field → 採用 concept localname

    @property
    def has_tier1_data(self) -> bool:
        """Tier 1 で 1 つでも値が取れたか? (False なら XBRL 解析失敗扱い)"""
        return any(
            v is not None
            for v in (
                self.net_sales,
                self.operating_profit,
                self.net_profit,
                self.total_assets,
                self.net_assets,
            )
        )


def parse_xbrl_zip(zip_bytes: bytes, *, document_id: str | None = None) -> XbrlFinancials:
    """EDINET XBRL zip (bytes) から Tier 1+2 を抽出する。

    Args:
        zip_bytes: `EdinetClient.download(content_type="xbrl_zip")` で取れる bytes
        document_id: ログ識別子 (任意)

    Returns:
        `XbrlFinancials`。 全項目 None で `has_tier1_data=False` の場合は
        失敗扱いで PDF fallback を検討する。

    Raises:
        ImportError: `[xbrl]` extras が未導入 (arelle-release が無い)
    """
    try:
        from arelle import Cntlr  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "arelle-release is required for XBRL parsing. "
            "Install edinet-client with [xbrl] extra: "
            "pip install 'edinet-client[xbrl]'"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="edinet_xbrl_") as tmp:
        tmp_path = Path(tmp)
        try:
            zip_path = tmp_path / "doc.zip"
            zip_path.write_bytes(zip_bytes)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile as exc:
            logger.warning(
                "invalid XBRL zip (document_id=%s): %s", document_id, exc
            )
            return XbrlFinancials()

        entry = _find_main_xbrl_file(tmp_path)
        if entry is None:
            logger.warning(
                "no .xbrl entry point found in zip (document_id=%s)", document_id
            )
            return XbrlFinancials()

        cntlr = Cntlr.Cntlr(logFileName=None)
        try:
            model = cntlr.modelManager.load(str(entry))
            if model is None or not getattr(model, "facts", None):
                logger.warning(
                    "Arelle returned empty model for document_id=%s", document_id
                )
                return XbrlFinancials()
            return _extract_financials(model)
        finally:
            try:
                cntlr.close()
            except Exception:  # noqa: BLE001
                pass


def _find_main_xbrl_file(root: Path) -> Path | None:
    """zip 展開後の root から **メインの有報 .xbrl** ファイルを探す。

    EDINET zip 慣例:
      XBRL/PublicDoc/jpcrp030000-asr-*.xbrl  (有報)
      XBRL/PublicDoc/jpcrp040300-q1r-*.xbrl  (四半期)
    """
    publicdoc = root / "XBRL" / "PublicDoc"
    if publicdoc.exists():
        candidates = sorted(publicdoc.glob("*.xbrl"))
        if candidates:
            return candidates[0]
    candidates = sorted(root.rglob("*.xbrl"))
    return candidates[0] if candidates else None


def _extract_financials(model: Any) -> XbrlFinancials:
    """Arelle ModelXbrl から Tier 1+2 を抽出する。"""
    facts_by_concept = _index_facts_by_concept_localname(model)

    period_info = _infer_period(facts_by_concept)
    consolidated_facts = _filter_consolidated(facts_by_concept)

    raw_hits: dict[str, str] = {}
    tier1: dict[str, float | None] = {}
    for field, concepts in _CONCEPT_CANDIDATES.items():
        value, concept_hit = _pick_first_value(
            consolidated_facts, concepts, prefer_period_end=period_info["period_end"]
        )
        tier1[field] = value
        if concept_hit:
            raw_hits[field] = concept_hit

    segments = _extract_segments(facts_by_concept, period_end=period_info["period_end"])

    return XbrlFinancials(
        fiscal_year_end=period_info["period_end"],
        period_type=period_info["period_type"],
        is_consolidated=period_info["is_consolidated"],
        net_sales=tier1.get("net_sales"),
        operating_profit=tier1.get("operating_profit"),
        ordinary_profit=tier1.get("ordinary_profit"),
        net_profit=tier1.get("net_profit"),
        total_assets=tier1.get("total_assets"),
        net_assets=tier1.get("net_assets"),
        segments=tuple(segments),
        raw_concept_hits=raw_hits,
    )


def _index_facts_by_concept_localname(model: Any) -> dict[str, list[Any]]:
    """`fact.concept.qname.localName` をキーに fact を index 化する。"""
    index: dict[str, list[Any]] = {}
    for fact in model.facts:
        try:
            localname = fact.concept.qname.localName
        except AttributeError:
            continue
        index.setdefault(localname, []).append(fact)
    return index


def _infer_period(facts_by_concept: dict[str, list[Any]]) -> dict[str, Any]:
    """書類の期末日 / 種別 / 連結フラグを推定する。"""
    period_end: date | None = None
    period_type: Literal["annual", "quarterly", "semi", "other"] = "other"
    is_consolidated = True

    # 期末日推定: jpdei_cor:CurrentFiscalYearEndDateDEI
    for concept_localname in (
        "CurrentFiscalYearEndDateDEI",
        "FiscalYearEnd",
    ):
        if concept_localname in facts_by_concept:
            fact = facts_by_concept[concept_localname][0]
            period_end = _parse_date_value(fact)
            if period_end:
                break

    # 種別推定: DocumentType DEI から
    for fact in facts_by_concept.get("DocumentTypeDEI", []):
        v = str(getattr(fact, "value", "") or "").lower()
        if "asr" in v or "annual" in v:
            period_type = "annual"
            break
        if "q" in v:
            period_type = "quarterly"
            break
        if "ssr" in v or "semi" in v:
            period_type = "semi"
            break

    # 連結 / 単体推定: WhetherConsolidatedFinancialStatementsArePreparedDEI
    for fact in facts_by_concept.get("WhetherConsolidatedFinancialStatementsArePreparedDEI", []):
        v = str(getattr(fact, "value", "") or "").lower()
        if v in ("false", "0"):
            is_consolidated = False
        break

    return {
        "period_end": period_end,
        "period_type": period_type,
        "is_consolidated": is_consolidated,
    }


def _filter_consolidated(
    facts_by_concept: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """連結 context (= NonConsolidatedMember dimension が付いていない) のみ残す。

    NonConsolidatedMember が付いている facts は単体 (= 親会社単体決算) なので除外。
    """
    filtered: dict[str, list[Any]] = {}
    for concept, facts in facts_by_concept.items():
        kept = [f for f in facts if not _has_non_consolidated_dimension(f)]
        if kept:
            filtered[concept] = kept
    return filtered


def _has_non_consolidated_dimension(fact: Any) -> bool:
    ctx = getattr(fact, "context", None)
    if ctx is None:
        return False
    for dim_value in getattr(ctx, "qnameDims", {}).values():
        member_qname = getattr(dim_value, "memberQname", None)
        if member_qname is None:
            continue
        if "NonConsolidatedMember" in str(member_qname.localName or ""):
            return True
    return False


def _pick_first_value(
    facts_by_concept: dict[str, list[Any]],
    candidates: tuple[str, ...],
    *,
    prefer_period_end: date | None = None,
) -> tuple[float | None, str | None]:
    """候補 concept を順に試して **最も当期に近い** value を返す。

    Returns:
        (value, hit_concept_localname) — 見つからなければ (None, None)
    """
    for concept in candidates:
        facts = facts_by_concept.get(concept, [])
        if not facts:
            continue
        non_segment = [f for f in facts if not _has_segment_dimension(f)]
        pool = non_segment or facts
        chosen = _pick_current_period_fact(pool, prefer_period_end=prefer_period_end)
        if chosen is None:
            continue
        value = _parse_numeric_value(chosen)
        if value is None:
            continue
        return value, concept
    return None, None


def _has_segment_dimension(fact: Any) -> bool:
    """セグメント / 報告セグメント次元が付いているか?

    Tier 1 取得時は、 セグメント別の分解値ではなく **会社全体合計** を取りたい。
    EDINET 標準では `OperatingSegmentsAxis` / `ReportableSegmentsAxis` /
    `BusinessSegmentsAxis` のいずれかでセグメント分解される。
    """
    ctx = getattr(fact, "context", None)
    if ctx is None:
        return False
    for axis_qname in getattr(ctx, "qnameDims", {}):
        local = str(getattr(axis_qname, "localName", "") or "")
        if local in _SEGMENT_AXIS_KEYWORDS:
            return True
    return False


def _pick_current_period_fact(
    facts: list[Any], *, prefer_period_end: date | None
) -> Any | None:
    """同じ concept の facts から **当期** に該当するものを 1 件選ぶ。

    優先順位:
    1. `prefer_period_end` と一致する context (EDINET の exclusive end 慣行で +1 日も許容)
    2. context.endDatetime が最も新しいもの
    3. それでも決まらなければ facts[0]
    """
    if not facts:
        return None

    if prefer_period_end:
        for fact in facts:
            if _matches_period_end(fact, prefer_period_end):
                return fact

    dated = [(f, _context_end_date(f)) for f in facts]
    dated_valid = [(f, d) for f, d in dated if d is not None]
    if dated_valid:
        dated_valid.sort(key=lambda pair: pair[1], reverse=True)
        return dated_valid[0][0]

    return facts[0]


def _matches_period_end(fact: Any, period_end: date) -> bool:
    """fact の context end が `period_end` と一致するか?

    EDINET XBRL は **exclusive end** 慣行 (e.g., FY ending 2025-03-31 →
    endDatetime=2025-04-01) を使うので、 `period_end == fact_end` だけでなく
    `period_end + 1 day == fact_end` も合致と見なす。
    """
    from datetime import timedelta  # noqa: PLC0415 — 局所利用

    ctx_end = _context_end_date(fact)
    if ctx_end is None:
        return False
    return ctx_end == period_end or ctx_end == period_end + timedelta(days=1)


def _context_end_date(fact: Any) -> date | None:
    ctx = getattr(fact, "context", None)
    if ctx is None:
        return None
    dt = getattr(ctx, "endDatetime", None) or getattr(ctx, "instantDatetime", None)
    if dt is None:
        return None
    try:
        return dt.date() if hasattr(dt, "date") else None
    except Exception:  # noqa: BLE001
        return None


def _parse_numeric_value(fact: Any) -> float | None:
    """fact.xValue / fact.value を float にする。 None / 'nan' / 非数値は None。"""
    raw = getattr(fact, "xValue", None)
    if raw is None:
        raw = getattr(fact, "value", None)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_date_value(fact: Any) -> date | None:
    raw = getattr(fact, "value", None)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _extract_segments(
    facts_by_concept: dict[str, list[Any]], *, period_end: date | None
) -> list[XbrlSegment]:
    """セグメント別の売上 / 営業利益を抽出する。

    EDINET XBRL では `OperatingSegmentsAxis` / `ReportableSegmentsAxis` /
    `BusinessSegmentsAxis` のいずれかの axis に member が乗ったコンテキストで
    セグメント値が表現される。 軸 member の localName からセグメント名を取る。

    集計 / 調整 member (`ReportableSegmentsMember` / `TotalOf...Member` /
    `EliminationsOrAdjustmentsMember` / `ReconcilingItemsMember` 等) は除外。
    """
    sales_per_segment: dict[str, float] = {}
    profit_per_segment: dict[str, float] = {}

    for concept in _SEGMENT_CONCEPTS["net_sales"]:
        for fact in facts_by_concept.get(concept, []):
            seg_name = _extract_segment_name(fact)
            if seg_name is None:
                continue
            if period_end and not _matches_period_end(fact, period_end):
                continue
            value = _parse_numeric_value(fact)
            if value is None:
                continue
            sales_per_segment.setdefault(seg_name, value)

    for concept in _SEGMENT_CONCEPTS["operating_profit"]:
        for fact in facts_by_concept.get(concept, []):
            seg_name = _extract_segment_name(fact)
            if seg_name is None:
                continue
            if period_end and not _matches_period_end(fact, period_end):
                continue
            value = _parse_numeric_value(fact)
            if value is None:
                continue
            profit_per_segment.setdefault(seg_name, value)

    all_segments = set(sales_per_segment) | set(profit_per_segment)
    segments: list[XbrlSegment] = []
    for name in sorted(all_segments):
        segments.append(
            XbrlSegment(
                segment_name=name,
                net_sales=sales_per_segment.get(name),
                operating_profit=profit_per_segment.get(name),
            )
        )
    return segments


def _extract_segment_name(fact: Any) -> str | None:
    """fact の context dimensional axis から **セグメント名** を取り出す。

    Recognized axes: `OperatingSegmentsAxis` / `ReportableSegmentsAxis` /
    `BusinessSegmentsAxis` (`_SEGMENT_AXIS_KEYWORDS`)。

    集計 / 調整 / 「その他」 系の member は `_SEGMENT_MEMBER_EXCLUDES` で除外。
    名前末尾の `ReportableSegmentsMember` / `Member` suffix を削って読みやすく。
    """
    ctx = getattr(fact, "context", None)
    if ctx is None:
        return None
    for axis_qname, dim_value in getattr(ctx, "qnameDims", {}).items():
        axis_local = str(getattr(axis_qname, "localName", "") or "")
        if axis_local not in _SEGMENT_AXIS_KEYWORDS:
            continue
        member_qname = getattr(dim_value, "memberQname", None)
        if member_qname is None:
            continue
        local = str(member_qname.localName or "")
        if not local:
            continue
        if local in _SEGMENT_MEMBER_EXCLUDES:
            continue
        for suffix in _SEGMENT_MEMBER_SUFFIXES:
            if local.endswith(suffix):
                local = local[: -len(suffix)]
                break
        return local
    return None


__all__ = [
    "XbrlFinancials",
    "XbrlSegment",
    "parse_xbrl_zip",
]
