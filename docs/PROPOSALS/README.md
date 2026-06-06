# Proposals (機能提案ドキュメント)

このディレクトリには、モノレポ内の各エージェント (driving-license-bot,
piyolog-analytics, lifeplanner-agent, etc.) に対する機能提案 / 設計判断を、
**KEP (Kubernetes Enhancement Proposal) ベースの軽量フォーマット** で記録する。

## 目的

- 「なぜ作ったか」「どう設計したか」「他にどんな案があったか」を後から追える
- PR を分割するときの設計ベースライン (1 つの提案 → 複数 PR)
- ADR (Architecture Decision Record) を兼ねる: `Alternatives` + `Implementation History`
  セクションで意思決定を記録
- 将来の品質管理 / 再設計時のリファレンス

## 書くタイミング

| 規模 | 書く？ |
|---|---|
| バグ修正、typo、軽微なリファクタ | ❌ 不要 (commit message + PR description で十分) |
| 1 PR で完結する小機能 (例: 新コマンド 1 個追加) | △ 任意 (LINE_ROADMAP.md 等の per-system roadmap で代替可) |
| 複数 PR にまたがる中規模機能 (例: PR 1 / PR 2 のような連番) | ✅ 推奨 |
| アーキテクチャに影響する変更 (DB スキーマ大改修、認証方式変更等) | ✅ 必須 |
| 新エージェント立ち上げ | ✅ 必須 (per-system design を兼ねる) |

## 運用ルール (forward-going)

「✅ 推奨」「✅ 必須」に該当する PR を出す前に、以下のフローを踏む:

1. **Draft 作成**: `TEMPLATE.md` をコピーして `NNNN-short-title.md` を作成、必須セクションを埋める。Status は `Draft`
2. **採番**: 採番台帳 (本ファイルの表) の最大値 + 1 を取り、ファイル名と本文の `# PROPOSAL-NNNN:` に反映。台帳に 1 行追加
3. **設計レビュー PR**: 提案 doc 単体で PR を作るのが理想 (Stage 1 のテンプレで実証済)。実装 PR を急ぐ場合は実装 PR と一括でも OK、その場合は PR description の冒頭に「設計: docs/PROPOSALS/NNNN-...md 参照」のリンクを必ず入れる
4. **Approved → Implementing**: レビュー OK 後、実装 PR を切る (ID は実装 PR の本文に記載)
5. **Implemented**: 全関連 PR がマージされたら Status を `Implemented` に更新し、`Implementation History` に PR 番号を追記

> **強制度**: 必須項目はレビュー時の指摘対象とする (上記ガイドの「✅ 必須」)。
> 推奨項目は判断委ねるが、後で「なぜそうした？」となりそうなら書いておく方が安全。

## Backfill (限定)

過去の重要 PR で proposal doc が未作成のものは、必要に応じて後追いで作成する
(沈没コスト回避のため、新規分を優先)。

| 番号 | タイトル | 対象 PR | 優先度 | 状態 |
|---|---|---|---|---|
| (予定) | piyolog 子情報 DB + 設定 UI | [#100](https://github.com/sakamoto-family-smile/agent_monorepo/pull/100) | 中 | Stage 2 (#109 piyolog 移行) 後に検討 |
| (予定) | lifeplanner LINE 分析コマンド | [#104](https://github.com/sakamoto-family-smile/agent_monorepo/pull/104) | 中 | Stage 2 完了後に検討 |

それ以外の過去 PR は backfill 不要 (commit log + PR description で十分追える)。

## 命名規則

```
docs/PROPOSALS/NNNN-short-kebab-title.md
```

- `NNNN`: 4 桁ゼロ埋めの連番 (`0001`, `0002`, ...)
  - 採番は merge 順 (PR 作成時に既存最大値 + 1 を取る)
  - 衝突した場合はリベース時に再採番
- `short-kebab-title`: 短い英語タイトル (3-5 単語、kebab-case)
  - 例: `0001-line-cashflow-display.md`
  - 日本語タイトルは proposal 本文 (`# PROPOSAL-NNNN: ...`) で書く

## 採番台帳

| Number | Title | Target | Status |
|---|---|---|---|
| [0001](0001-lifeplanner-cashflow-breakdown.md) | キャッシュフロー粒度向上 | lifeplanner-agent | Implemented |
| [0002](0002-deepteam-redteam-replacement.md) | red team を Promptfoo から DeepTeam に置き換え | security-platform | Draft |
| [0003](0003-fujisawa-platform-shared-base.md) | 藤沢市データ共通基盤 fujisawa-platform | cross-agent (新規) | Draft |
| [0004](0004-fujisawa-info-bot.md) | 藤沢市情報 LINE Bot | fujisawa-info-bot (新規) | Draft |
| [0005](0005-fujisawa-hokatsu-agent.md) | 藤沢市保活エージェント | fujisawa-hokatsu-agent (新規) | Draft |
| [0006](0006-edinet-integration.md) | EDINET 統合 (金融庁開示書類で stock-analysis-agent を強化) | stock-analysis-agent + edinet-client (新規) | Implemented |
| [0007](0007-paper-qa-agent.md) | 論文検索 QA エージェント + 共通基盤 paper-platform | paper-qa-agent (新規) + paper-platform (新規 cross-agent) | Draft |
| [0008](0008-llm-security-lab.md) | OWASP LLM Top 10 体験学習ラボ llm-security-lab | llm-security-lab (新規教材) | Draft |
| [0009](0009-gcp-cost-optimization.md) | GCP コスト最適化（Cloud SQL 集約ほか） | cross-agent (GCP インフラ全体) | Implementing |
| [0010](0010-analytics-platform-phase5-event-persistence.md) | analytics-platform Phase 5 完遂（Pub/Sub 入口 + 本番イベントの GCS 永続化） | cross-agent (analytics-platform + 稼働中エージェント) | Implementing |
| [0011](0011-stock-analysis-agent-line-gcp.md) | stock-analysis-agent を LINE 経由で使えるよう GCP に配備 | stock-analysis-agent | Draft |

新しい提案を作るたびに上記表に 1 行追加する (forget-me-not)。

## ステータス遷移

```
Draft → In Review → Approved → Implementing → Implemented
                              ↓
                          Rejected / Deprecated
```

| ステータス | 意味 |
|---|---|
| **Draft** | 執筆中。レビュー前 |
| **In Review** | PR を出してレビュー待ち |
| **Approved** | レビュー OK、実装着手前 |
| **Implementing** | 実装中 (PR 着手済) |
| **Implemented** | 実装完了 (関連 PR がすべて merged) |
| **Rejected** | 不採用 (理由を `Drawbacks` セクションに残す) |
| **Deprecated** | 古くなって無効。後継提案へのリンクを残す |

## 書き方ガイド

1. `TEMPLATE.md` をコピー → `NNNN-your-title.md` にリネーム
2. **必須セクション**は全部埋める (空の節は削除しない、N/A と書く)
3. **推奨セクション**は該当する場合のみ埋める。空なら削除して構わない
4. PR 開いて design レビューを受ける
5. Approved になったら実装 PR で `Implementing` → `Implemented` に更新
6. 実装 PR で発覚した設計変更は提案 doc を更新 (sticky doc 方針)

## 必須 / 推奨 / 不要 の判断基準

KEP 全項目を、本モノレポ (個人 / 家族向け、Cloud Run + Cloud SQL のシンプル
構成) の規模に合わせて以下で分類済:

### [必須] 必須セクション

- **Title / Summary / Motivation / Goals / Non-Goals** — どんな提案でも基本
- **Proposal / Design Details** — 設計内容
- **Risks and Mitigations** — データ消失・PII 漏洩・LLM 暴走など個人用途でも事故ると痛い
- **Test Plan** (pytest unit / integration) — 最低限の品質ゲート
- **Alternatives** — 設計判断の根拠 (ADR を兼ねる)
- **Implementation History** — PR 番号 + 日付の更新履歴

### [推奨] 推奨セクション (該当する場合のみ書く)

- **User Stories** — 家族メンバー視点のユースケース 1-2 個
- **Notes/Constraints/Caveats** — 既知の制約 (例: 「年単位粒度」)
- **Migration / Rollback** — alembic migration の方針、env 削除手順
- **Feature Enablement** — env / config で ON/OFF できるか
- **Monitoring (簡易)** — どのログ / Cloud Logging クエリで動作確認できるか
- **Troubleshooting (簡易)** — よくある詰まりどころ
- **Dependencies** — LINE / Vertex AI / 他エージェント連携の依存先
- **Non-Functional Requirements (機能個別)** — 性能 / コスト / プライバシー / キャパシティ。システム全体 NFR (月額予算等) は per-system design template (将来作成) に書く
- **Drawbacks** — 不採用の主張があるとき

### [不要] 不要セクション (Kubernetes 特有 / 個人プロジェクト規模で過剰)

- **Release Signoff Checklist** — Kubernetes リリースサイクル特有
- **Graduation Criteria (Alpha/Beta/GA)** — feature gate のグラデーションは過剰
- **Version Skew Strategy** — 単一プロセス + 単一クラスタには不要
- **Scalability の細かい質問** (API call 数、cloud provider 呼出回数等) — 規模に対し overkill
- **PRR の細かい SLI/SLO 数値目標** — 「動けば良し」レベルで十分
- **Infrastructure Needed** — SIG / プロジェクトリソース要求の話で個人にはない

詳細は `TEMPLATE.md` のコメントを参照。

## 既存ドキュメントとの関係

| 既存 doc | 関係 |
|---|---|
| 各エージェントの `README.md` | システム全体の使い方。本テンプレとは別軸 (将来 README テンプレも作る予定 → §「将来計画」参照) |
| `piyolog-analytics/docs/design.md` | per-system 設計書。本テンプレとは粒度が違う (per-feature ではなく per-system) |
| `piyolog-analytics/docs/SETTINGS.md` / `BACKUP_RESTORE.md` | 機能個別の運用ガイド。本テンプレで書き直すか / そのまま運用ガイドとして残すかは段階的に判断 |
| `lifeplanner-agent/docs/LINE_ROADMAP.md` | 複数 PR を束ねる roadmap。本テンプレの "Implementation History" + 一覧表 で代替可 |

**移行方針**:
- 既存 doc は **そのまま残す** (沈没コストを払わない)
- 新規 / 大きめの再設計時に本テンプレを使う
- 余裕があれば既存 doc を **段階的にテンプレ準拠に書き換える** (優先度低)

## 将来計画

- [ ] **Per-system design template** (`docs/SYSTEM_DESIGN_TEMPLATE.md`):
  - 1 エージェント全体の機能要件 / 非機能要件 / アーキテクチャ図 を書く
  - 既存 `piyolog-analytics/docs/design.md` をベースに項目抽出
- [ ] **README template** (`docs/README_TEMPLATE.md`):
  - 各エージェントの README フォーマット統一
  - Quickstart / API / env / セットアップ手順 / 運用 の構成を共通化
- [ ] **ADR (個別意思決定)**: 上記 per-feature proposal が大きくなりすぎる場合、ADR
  を別ディレクトリ (`docs/ADR/`) に切り出すかを検討
