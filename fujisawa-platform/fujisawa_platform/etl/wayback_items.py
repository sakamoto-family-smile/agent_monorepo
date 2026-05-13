"""wayback_backfill 用の BackfillItem 固定リスト (Phase 4-2h step 3-2)。

`wayback_backfill` Job は **一度きり** 実行のため、対象 PDF を env や引数で渡すより、
コード内に固定リストとして持つ方がレビュー履歴 / 再現性の観点で扱いやすい。

現状の収録範囲: **令和 4 年最低内定指数 PDF (`r4-4nyuusyonaiteisisuu.pdf`) のみ**。

- investigation note §A2 (`docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md`)
  で発掘した「令和 4 年限定で施設×クラス別の最低内定指数が完全公表されていた」事実 (M8) を
  受け、proposal 0005 §9.5 のハイブリッドモデル (過去基準 + 直近 3 年推定) に必要な
  唯一の Wayback バックフィル対象。
- CDX API (`web.archive.org/cdx/search/cdx`) で取得した実 timestamp:
  `20220308001221` (2022-03-08 snapshot, mimetype application/pdf, 184,967 bytes)。
- 令和 5-6 年の `akizyoukyou*.pdf` / `mousikomizyoukyou*.pdf` も Wayback で取得可能
  であることは investigation note §A2-1 / §A2-4 で確認済 (現サイト側は両 URL パターン
  とも 404 で消失していることを 2026-05-13 に再確認)。ただし以下が未解決のため、
  本リストには含めず別 PR で追加予定:
  - 8 件 (R5×4 + R6×4) の 14 桁 Wayback timestamp の個別確定 (CDX クエリ)
  - `BackfillKind="regular"` (`parse_admission_table`) が `akizyoukyou*` /
    `mousikomizyoukyou*` の表構造を扱えるかの Docling 実抽出検証
    (`biyearly_admission_etl` 想定の「4 月入所結果 PDF」と構造が同じか、種別ごとに
    新 `BackfillKind` を切るかは事前判定が必要)

追加収録時の手順:
  1. `curl 'http://web.archive.org/cdx/search/cdx?url=<original_url>&output=json&limit=20'`
     で実 timestamp を確定
  2. `BackfillItem` を本リストに append
  3. `tests/etl/test_wayback_items.py` の不変条件を更新
"""

from __future__ import annotations

from fujisawa_platform.etl.wayback_backfill import BackfillItem

# 令和 4 年 (2022) 1 次入所内定指数 PDF。
# - 投資 note §A2-2: 「3 ページ・220 KB・120+ 施設収録」
# - CDX 確認時 (2026-05-13) の length: 184,967 bytes
_R4_MIN_INDEX = BackfillItem(
    kind="min_index_2022",
    wayback_timestamp="20220308001221",
    original_url="https://www.city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf",
    year=2022,
    round="1st",
)

# Cloud Run Job (`cli.py`) から import される runtime item リスト。
# 順序は items_processed の出力安定性のため固定。
RUNTIME_ITEMS: tuple[BackfillItem, ...] = (_R4_MIN_INDEX,)


__all__ = ["RUNTIME_ITEMS"]
