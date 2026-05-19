# Fujisawa Platform Follow-up Backlog (R4 backfill 完了後)

**作成日**: 2026-05-19
**作成者**: @kurama554101 + Claude Code 共同作業セッション (2026-05-13〜2026-05-19) のまとめ
**Status**: open backlog

このノートは Phase 4-2h step 3 deploy 後の本番運用で顕在化した不具合 fix と、 そこから派生した
follow-up タスクの**横断的追跡**を目的とする。 各 PR description の "Out of scope" 節に散在して
いた未着手項目を 1 箇所に集約し、 進捗・優先度・受入条件を可視化する。

---

## A. このセッションで完了した PR (履歴)

時系列順:

| PR | Title | 主旨 |
|---|---|---|
| #132 | `feat(fujisawa-platform): wayback_items 注入で wayback_backfill を実 working 化` | R4 PDF 1 件の `BackfillItem` 固定リスト |
| #133 | `fix(fujisawa-platform): Dockerfile に Docling 用 system libs を追加` | `libxcb1` / `libgl1` / `libgomp1` / `libglib2.0-0` |
| #135 | `fix(fujisawa-platform): R4 min_index parser を実 Docling 出力に合わせて修正` | header 全角/半角・歳児/歳・Docling header miss 救済 |
| #136 | `fix(fujisawa-platform): terraform variable default を本番運用値に更新` | facility URL 2 種 + `etl_job_memory` 4Gi |
| #137 | `feat(fujisawa-platform): Cloud Build 設定をリポジトリに永続化` | `cloudbuild.yaml` + `cloudbuild.gcloudignore` |
| #138 | `feat(ci): fujisawa-platform 用 PR Tests / Terraform validate ジョブを追加` | CI 上の Test / Terraform fmt+validate |
| #139 | `fix(fujisawa-platform): facility 表記揺れ alias を R4 backfill 用に投入` | `R4_FACILITY_ALIASES` 11 件 + parser merge |
| #140 | `fix(fujisawa-platform): FacilitiesRepo.replace_all を UPSERT + 条件付き DELETE に変更` | FK violation 解消 + 設計書 (proposal 0003 §4.5.5 / DESIGN.md §9.0/§9.1) 追従 |

最終状態: `facilities` 157 行 / `admission_results` (year=2022) 198 行 / 91 unique facilities。

---

## B. 未着手 follow-up (優先度別)

### B-1 (中) — 設計品質・運用安全

| # | 項目 | 概要 | 受入条件 | 関連 |
|---|---|---|---|---|
| B-1-1 | terraform plan CI workflow (Phase 4-2h step 4 完成形) | WIF 認証 + plan を CI で実行し PR コメントに出力。 fujisawa-platform 用 SA / `wif.tf` 整備が必要 | `Terraform plan / fujisawa-platform` job が PR で plan output を comment | PR #138 (fmt/validate 段階のみ実装済) |
| B-1-2 | terraform 個人 tfvars と production の整合性監査 | このセッションで `gcloud run jobs update` で手動投入した値 (image SHA / WAYBACK_BACKFILL_ENABLED 等) が terraform state と乖離している可能性 | 個人 tfvars に etl_image / 各種 URL を反映 → `terraform plan` を no-op 化 | PR #136 |
| B-1-3 | yearly_navi / biyearly_admission の実 URL 確定 | terraform.tfvars の `etl_navi_pdf_url` / `etl_admission_pdf_url_1st` / `etl_admission_pdf_url_2nd` が現状 `""`。 対応 Job がまだ稼働実績なしのため URL 未確定 | URL 確定 → `variables.tf` default に投入 → 実 Job 実行で `rows_written > 0` 確認 | PR #136 (Out of scope) |
| B-1-4 | retired facility に soft-delete column を追加 | PR #140 で「下流参照がある facility は DELETE しない」 対応をしたが、 これらは active と区別できない。 `is_active boolean` 等で明示する設計改善 | スキーマに `is_active` 追加 + 移行 SQL + 関連 query 更新 | PR #140 (Out of scope) |

### B-2 (低) — R4 backfill 完成度向上

| # | 項目 | 概要 | 受入条件 | 関連 |
|---|---|---|---|---|
| B-2-1 | family-care `0歳～2歳` range header parser 対応 | min_index_parser が range header (3 age を 1 列) を skip 中。 該当は家庭的保育の 2 施設のみで data がほぼ `○`/`-` マーカー、 実質効果は小 | range header から 0/1/2 の 3 entries を生む or 明示的に skip 設計を確定 | PR #135 (Out of scope) |
| B-2-2 | 残 5-7 件の R4 facility 救済 | (a) 閉園扱い `アスク鵠沼保育園`、 (b) 真の新設 `きっずワンフレンズ・メイト保育園`、 (c) Docling header 誤抽出 `法人立` | (a) NoMatch を許容、 (b) facility ETL 側で resolver alias を拡張、 (c) `min_index_parser` で `法人立` 等のカテゴリ語を skip | PR #139 (Out of scope) |
| B-2-3 | `わかたけ第２保育園` の誤 match 抑止 | DB に対応 facility が無く resolver が `わかたけ保育園` (別物) と fuzzy 一致してしまう。 PR #140 後の現状は OK だが将来の再発防止 | resolver threshold 調整 or 閉園扱い facility の明示 | PR #139 (検証時に確認) |

### B-3 (中) — R5-6 wayback backfill

| # | 項目 | 概要 | 受入条件 | 関連 |
|---|---|---|---|---|
| B-3-1 | R6 (2024) PDF 4 件の Wayback バックフィル | `akizyoukyou20240401-1a/2.pdf` + `mousikomizyoukyou20240401-1/2.pdf` の 4 件は CDX で実 timestamp 確定済 (R5-6 follow-up 調査結果)。 parser 互換性 (`BackfillKind="regular"` で受けられるか) を Docling 実抽出で検証してから `RUNTIME_ITEMS` に追加 | `wayback_items.py` に R6 entries 追加 + `admission_results` に R6 rows が入る | task #1 のセッション内調査結果 |
| B-3-2 | R5 (2023) PDF が Wayback アーカイブ無い件の文書化 | investigation note §A2-1 では R5 PDF も backfill 対象として列挙されていたが、 実際は Wayback にも無い。 note 訂正が必要 | investigation note §A2-1 を「URL 列挙 ≠ archive 存在」に訂正、 `proposal 0005 §9.5` ハイブリッドモデルへの影響を再評価 | task #1 のセッション内調査 |

### B-4 (低) — 周辺整備

| # | 項目 | 概要 | 受入条件 | 関連 |
|---|---|---|---|---|
| B-4-1 | `fujisawa-etl:verify` 残骸 tag 削除 | PR #137 verify build で push した tag が Artifact Registry に残っている | `gcloud artifacts docker tags delete` 1 発 | PR #137 |
| B-4-2 | `monthly_vacancy_etl` の `vacancy_pdf_url` env 1 つ持ち設計見直し | 履歴バックフィルできない設計上の問題。 月次 URL リストを別管理する設計に変更 | URL リスト管理機構を導入 + bulk backfill 想定 | PR #132 (Out of scope) |

### B-5 (大) — 下流 consumer エージェント

| # | 項目 | 概要 | 受入条件 | 関連 |
|---|---|---|---|---|
| B-5-1 | 0004 (fujisawa-info-bot LINE) 着手 | Cloud Run service として独立稼働、 本基盤を path dep で import する consumer | proposal 0004 Phase 1 完了 | proposal 0004 |
| B-5-2 | 0005 (fujisawa-hokatsu agent) Phase 1 着手 | Score-Calc / Cost-Calc / IntakeAgent (P0 機能) | proposal 0005 Phase 1 完了 | proposal 0005 |

---

## C. 進捗管理ルール

- 本ノートは **作成日時固定** (`*-2026-05-19.md`)、 各項目の完了は **完了 PR 番号 + 完了日** を表に追記する形で記録する
- 完了後の項目も表から削除せず、 strikethrough にして履歴を保持する
- 新規発見の follow-up は本ノートに追加して良いが、 大幅に増えるようなら別ノートに切り出す
- メモリ (`MEMORY.md`) には本ノートへの 1 行 pointer のみ置く
