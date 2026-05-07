# ドキュメント移行リファクタリング計画

既存ドキュメントを `docs/PROPOSALS/`, `docs/SYSTEM_DESIGN_TEMPLATE.md`,
`docs/README_TEMPLATE.md` に段階的に寄せる計画書。

## 現状の課題

ドキュメント監査結果 (2026-05 時点、49 ファイル):

| カテゴリ | 件数 | 課題 |
|---|---|---|
| README (各エージェント + repo root) | 11 | フォーマット不統一、巨大化 (lifeplanner 570 行 / analytics 950 行) |
| Per-system design | 7 | テンプレ未整備、README に埋め込みなのか別 doc なのかブレ |
| Per-feature proposal / ADR | 0 → 1 | テンプレ整備済 (PR #106)、これから書き起こす |
| Operations runbook (deploy / backup / setup) | 8 | テンプレ未整備、構造が似ているので寄せ可 |
| Roadmap | 6 | per-system design の節に統合する方針 |
| その他 (policies / skills / 設定) | 17 | 個別性高、テンプレ化困難 → 現状維持 |

## 移行ステージ

### Stage 1: テンプレ整備 ✅ (本 PR)

- [x] PR #106: per-feature proposal template (`docs/PROPOSALS/TEMPLATE.md`)
- [x] PR #107: per-system design template (`docs/SYSTEM_DESIGN_TEMPLATE.md`)
- [x] PR #107: README template (`docs/README_TEMPLATE.md`)
- [x] PR #107: ドキュメントテンプレ index (`docs/README.md`)

### Stage 2: 主要 3 エージェント移行

優先順位は doc 規模 (大きいほど効果大) と運用優先度で決定:

| 順 | エージェント | 既存 doc | 移行内容 | 状態 |
|---|---|---|---|---|
| 1 | **lifeplanner-agent** | README 895 行 (Quickstart + 機能要件 + Phase + アーキ全部入り) | README から機能要件 / Phase / アーキを `docs/DESIGN.md` に分離。README は Quickstart 中心に圧縮 | ✅ PR #108 |
| 2 | **piyolog-analytics** | `docs/design.md` 既存 | 新テンプレ準拠の `docs/DESIGN.md` に置換 (旧 design.md 削除)。NFR 7 節 + ADR-lite + 用語集追記 | ✅ PR #110 |
| 3 | **driving-license-bot** | `docs/DESIGN.md` 既存 (体系的、1028 行) | ヘッダ + 変更履歴 + Executive Summary + 目的・スコープ追加、§16 NFR / §17 ADR-lite / §18 関連 docs / §19 用語集 を末尾新設 (§0〜§15 は anchor 互換のため番号維持)。既存 11 docs は維持 | ✅ PR #111 |

### Stage 3: 残エージェント + Operations + README 統一

| 順 | 内容 |
|---|---|
| 4 | analytics-platform: README 950 行から DESIGN.md を抽出 (規模最大、最後に回す) |
| 5 | stock-analysis-agent / tech-news-agent / hotcook-agent: 各 README から DESIGN.md を抽出 (規模中) |
| 6 | security-platform / llm-client / kanie-lab-agent: 各 README から DESIGN.md を抽出 (規模小) |
| 7 | `docs/OPERATIONS_TEMPLATE.md` 作成 + 既存 ops doc (DEPLOY / SETUP / BACKUP_RESTORE) を寄せる |
| 8 | 全エージェント README を `README_TEMPLATE.md` のフォーマットに合わせる |

## PR 単位

各エージェント / 主要トピックごとに 1 PR、所要 7-8 PR を想定:

```
✅ PR #106          per-feature proposal template (KEP-based)
⏳ PR #107 (本 PR)  per-system design + README templates
⏳ PR #108          lifeplanner-agent 移行
⏳ PR #109          piyolog-analytics 移行
⏳ PR #110          driving-license-bot 移行
⏳ PR #111          analytics-platform 移行
⏳ PR #112          残エージェント (stock / tech-news / hotcook / security / llm-client / kanie) 移行
⏳ PR #113          OPERATIONS_TEMPLATE.md + 既存 ops doc 寄せ
⏳ PR #114          README フォーマット統一 (全エージェント)
```

進行は **1 PR ずつ merge → 次** の順。各 PR で得た学び (テンプレの足りない節 / ノイズ) は
テンプレ doc にフィードバック反映。

## Per-feature proposal doc の運用方針

per-feature proposal doc (`docs/PROPOSALS/NNNN-*.md`) は **forward-going が原則**。
過去 PR の backfill は限定的に行う:

- **forward-going**: 「✅ 推奨」「✅ 必須」規模の新規 PR は Draft → 設計レビュー → 実装の流れ。詳細ルールは [`docs/PROPOSALS/README.md`](PROPOSALS/README.md) の「運用ルール」節
- **backfill 対象 (2 件)**:
  - PR #100 piyolog 子情報 DB + 設定 UI (Stage 2 piyolog 移行後)
  - PR #104 lifeplanner LINE 分析コマンド (Stage 2 完了後)
- **その他過去 PR は backfill 不要** (commit log + PR description で追える範囲)

## 既存ドキュメントの扱い (沈没コスト回避)

| 既存 doc | 移行後の扱い |
|---|---|
| `<agent>/README.md` | テンプレ準拠に再構成 (Quickstart 主体に圧縮) |
| `<agent>/docs/design.md` 等 | テンプレ準拠の `DESIGN.md` にリネーム or 内容寄せ |
| `<agent>/docs/SETTINGS.md` / `BACKUP_RESTORE.md` 等 | 運用 doc として残す (Stage 3 で OPERATIONS テンプレに寄せる) |
| `<agent>/docs/POLICIES/` (privacy / terms) | テンプレ対象外、そのまま維持 |
| `<agent>/docs/*ROADMAP*.md` | per-system DESIGN.md の Roadmap 節からリンク (中粒度の roadmap は別 doc 維持) |
| `kanie-lab-agent/.claude/skills/*.md` | テンプレ対象外 (Claude skill 定義) |
| `hotcook-agent/data/skills/*.md` | テンプレ対象外 (MCP skill 定義) |

## 進捗トラッキング

各 PR でこのファイルの「Stage 2 / Stage 3」表のチェックボックスを更新。
完了したら `[x]` と PR 番号を記入する。

| エージェント | DESIGN.md | README リフレッシュ | OPERATIONS 寄せ |
|---|---|---|---|
| lifeplanner-agent | [x] PR #108 | [x] PR #108 | [ ] |
| piyolog-analytics | [x] PR #110 | [x] PR #110 | [ ] |
| driving-license-bot | [x] PR #111 | [x] PR #111 | [ ] |
| analytics-platform | [ ] | [ ] | [ ] |
| stock-analysis-agent | [ ] | [ ] | [ ] |
| tech-news-agent | [ ] | [ ] | [ ] |
| hotcook-agent | [ ] | [ ] | [ ] |
| kanie-lab-agent | [ ] | [ ] | [ ] |
| security-platform | [ ] | [ ] | [ ] |
| llm-client | [ ] | [ ] | [ ] |
