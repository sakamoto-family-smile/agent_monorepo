# agent_monorepo

エージェント関連のプロジェクトコード一式。各サブプロジェクトは独立して開発・デプロイ可能だが、共通のセキュリティ基盤 (`security-platform`) 配下で脆弱性監視と MCP トラフィック検査を行う。

## プロジェクト一覧

| プロジェクト | 種別 | 概要 | 分析基盤連携 |
|---|---|---|---|
| [`kanie-lab-agent`](./kanie-lab-agent/) | 実装 | 慶應 SFC 蟹江研究室 大学院入試準備の研究支援エージェント | ⬜ 未着手 |
| [`stock-analysis-agent`](./stock-analysis-agent/) | 実装 | 日本株・米国株のテクニカル/ファンダメンタル/センチメント統合分析エージェント | ✅ 連携済 (PR #26) |
| [`lifeplanner-agent`](./lifeplanner-agent/) | 実装 | Money Forward ME 起点の家族向けライフプランニング・30年シミュレーションエージェント | ✅ 連携済 (PR #27) |
| [`hotcook-agent`](./hotcook-agent/) | 実装 | シャープ ホットクック (KN-HW24H) の食材ベース料理提案エージェント (Phase 1) | ✅ 連携済 (PR #31) |
| [`piyolog-analytics`](./piyolog-analytics/) | 実装 | ぴよログ (育児記録) を LINE Bot 経由で取り込んで家族で横断サマリ共有 (Phase 1) | ✅ 連携済 (PR #34) |
| [`tech-news-agent`](./tech-news-agent/) | 実装 | データ基盤領域ニュース・論文の日次 LINE 配信 + 将来 QA 検索 (Phase 1 MVP) | ✅ 連携済 (本 PR) |
| [`driving-license-bot`](./driving-license-bot/) | 実装 | 運転免許（仮免・本免）学科試験対策 LINE Bot。Vertex AI Gemini で問題を自動生成し根拠条文・教則ページを必ず添付 (Phase 0 基盤整備) | ✅ 連携済 |
| [`security-platform`](./security-platform/) | 基盤 | 全エージェント共通のセキュリティ基盤（MCP Proxy / CVE 監視 / DLP / Red Team） | — (基盤側) |
| [`analytics-platform`](./analytics-platform/) | 基盤 | 全エージェント横断の分析基盤（OTel + Phoenix + JSONL + DuckDB + dbt、ローカル版のみ） | — (基盤側、Phase 1-4 完了 / Phase 5+ 未着手) |
| [`llm-client`](./llm-client/) | 基盤 | 薄い Anthropic Claude API ラッパ (prompt caching / 複数ターン / on_call フック)。モノレポ横断で再利用 | — (基盤側) |
| [`fujisawa-platform`](./fujisawa-platform/) | 基盤 | 藤沢市 HP / PDF を一次ソースとする共通基盤ライブラリ（クロール / PDF 解析 / pgvector ベクトル検索 / 出典 Skill / 表記ゆれ吸収 / ETL）。`fujisawa-info-bot` / `fujisawa-hokatsu-agent` から path dep で参照される想定 (Phase 4-2h step 3 実装済) | — (基盤側) |
| [`agent-system-1`](./agent-system-1/) | ダミー | 雛形（Research Assistant スキル用スケルトン） | — |
| [`agent-system-2`](./agent-system-2/) | ダミー | 雛形（Code Helper スキル用スケルトン） | — |

---

## 各エージェントの機能サマリ

### `kanie-lab-agent` — 蟹江研究室 大学院入試準備エージェント

慶應 SFC 政策・メディア研究科 蟹江憲史研究室（SDGs / 環境政策ガバナンス）への入学を目指す志願者を支援する Web アプリケーション。

**主な機能**
- **研究テーマ設計支援**: SDGs・環境政策・子ども政策の研究テーマ検討
- **論文サーベイ**: arxiv / Semantic Scholar / paper-search / e-Stat / e-Gov 法令を横断
- **面接対策**: 研究計画の模擬面接と厳格なフィードバック
- **研究計画レビュー**: 7軸評価による改善支援（追加引用の実在を MCP で確認）

**スタック**: Next.js 15 / FastAPI / Claude Agent SDK (Claude Sonnet 4.6) / Firebase Auth + Firestore / MCP (google-search, brave-search, paper-search, arxiv, semantic-scholar, e-stat, e-gov-law, fetch)

詳細: [`kanie-lab-agent/README.md`](./kanie-lab-agent/README.md)

---

### `stock-analysis-agent` — 株価分析エージェント

日本株（東証）・米国株（NASDAQ/NYSE）を対象に、企業名/ティッカーから自動で銘柄解決し、テクニカル・ファンダメンタル・センチメントを統合した日本語分析レポートを生成するエージェント。

**主な機能**
- **ティッカー解決**: 正規表現 → ローカル辞書 → yfinance Search → LLM の4段フォールバック
- **データ収集**: yfinance による日次 OHLCV・ファンダメンタルズ、Brave Search MCP 経由のニュース/センチメント
- **テクニカル指標**: SMA / EMA / RSI / MACD / ボリンジャーバンド（純 pandas 実装）
- **チャート生成**: mplfinance でローソク足 + 指標の画像出力
- **LLM 統合解説**: Claude Opus 4.6 (Vertex AI) が日本語で統合レポート生成
- **ユニバーススクリーナー**: 日本株 / 米国株 / グロース銘柄の一括スクリーニング（`data/universe/*.json`）

**スタック**: Python 3.12 / FastAPI / Claude Agent SDK (Claude Opus 4.6 via Vertex AI) / yfinance / pandas / mplfinance / SQLite / MCP (brave-search)

詳細: [`stock-analysis-agent/README.md`](./stock-analysis-agent/README.md)

---

### `lifeplanner-agent` — ライフプランナーエージェント

Money Forward ME の家計データを起点に、家族単位で30〜50年のキャッシュフロー・純資産推移をシミュレーションし、ライフイベント（出産・住宅購入・車買替等）の影響を定量比較する対話型エージェント。

**主な機能**
- **MF ME CSV 取込**: 収入・支出詳細 CSV を Shift-JIS/UTF-8 自動判定で取込
- **ダッシュボード**: 月次サマリ・カテゴリ別集計・異常検知・純資産スナップショット
- **世帯プロファイル管理**: メンバー/資産/負債の CRUD
- **ライフイベントシミュレーション**: 住宅購入 (E02)・車買替 (E04) を Phase 2 で実装済。Phase 4 で出産・進学・転職等を順次追加
- **30年プロジェクション**: 決定論的な長期シナリオ試算（給与成長率・インフレ率・投資利回り）
- **シナリオ比較**: 複数シナリオの決定論的差分 + LLM 自然言語要約
- **日本税制**: 所得税・住民税・社保（2026 年版 YAML、年版管理）
- **LLM アドバイザー**: Anthropic API 直呼 / GCP Vertex AI を `LLM_PROVIDER` で切替

**スタック**: Python 3.12 / FastAPI / SQLAlchemy async / Alembic / Anthropic SDK (Claude Sonnet 4.6、Vertex AI オプション) / Docker Compose / PostgreSQL (本番) / SQLite (ローカル)

詳細: [`lifeplanner-agent/README.md`](./lifeplanner-agent/README.md)

---

### `hotcook-agent` — ホットクック対応エージェント (Phase 1)

シャープ ヘルシオ ホットクック KN-HW24H を活用した、食材ベースの料理提案エージェント。冷蔵庫にある食材から、ホットクックで作れるメニューをランキング形式で提案する。

**主な機能 (Phase 1)**
- **食材入力 → レシピ提案**: 30 件の内蔵メニューシードからマッチ度 / 調理時間 / 予約可否でスコアリング
- **食材表記ゆれの正規化**: じゃがいも / ジャガイモ / じゃが芋 / 馬鈴薯 / potato → `jagaimo` タグに吸収
- **フィルタ**: 調理時間上限 / 予約調理必須 / まぜ技ユニット不要
- **在庫管理 (基礎 CRUD)**: Phase 2 の消費期限ベース優先提案の準備
- **メニューカタログ**: シャープ公式情報から事実情報のみ抽出した JSON (手順・分量は格納せず、ユーザーを公式参照へ誘導)

**スタック**: Python 3.12 / FastAPI / Pydantic / SQLite / Claude Agent SDK (Phase 2 以降で agent モード導入予定)

**ロードマップ**: Phase 1 (ローカル MVP) → Phase 2 (Web UI + 写真在庫) → Phase 3 (献立計画 + LangGraph) → Phase 4 (GCP 移行) → Phase 5 (マルチユーザー) → Phase 6 (高度化)

詳細: [`hotcook-agent/README.md`](./hotcook-agent/README.md)

---

### `piyolog-analytics` — ぴよログ分析エージェント (Phase 1)

育児記録アプリ「ぴよログ」の .txt エクスポートを LINE Bot 経由で取り込み、夫婦 2 人の LINE userId を同じ家族として集計し、授乳・睡眠・排泄・体重等の期間サマリを LINE テキストで返信するエージェント。

**主な機能 (Phase 1)**
- **LINE ファイル取り込み**: `.txt` 添付 → パース → SQLite に冪等 UPSERT
- **期間サマリ**: `今日` / `昨日` / `週間` / `月間` / `期間 YYYY-MM-DD YYYY-MM-DD` コマンド
- **家族共有**: `FAMILY_USER_IDS` で複数 userId を同じ `family_id` に束ねて集計
- **アクセス制御**: 許可リスト外ユーザは silent drop
- **冪等化**: `event_id = sha1(family + ts + type + raw)` と原本ハッシュで重複取込を防止
- **観測性連携**: `analytics-platform` に webhook 受信・取り込み成否を emit

**スタック**: Python 3.12 / FastAPI / aiosqlite / line-bot-sdk v3 / pydantic-settings / analytics-platform (path dep)

**ロードマップ**: Phase 1 (MVP) → Phase 1.5 (グラフ + ロールバック) → Phase 2 (リッチメニュー) → Phase 3 (Claude 相談 + 緊急キーワードゲート)

詳細: [`piyolog-analytics/README.md`](./piyolog-analytics/README.md)

---

### `tech-news-agent` — 技術ニュース配信エージェント (Phase 1 MVP)

データ基盤領域 (BigQuery / Snowflake / dbt / Iceberg / Databricks / データ品質 / データガバナンス 等) のニュースと論文を毎日 LINE に配信するパーソナル情報配信サービス。将来ドメインはセキュリティ / クラウド / LLM 動向に拡張予定。

**主な機能 (Phase 1 MVP)**
- **RSS 収集**: Google Cloud / AWS / Databricks / Snowflake / Zenn の主要 5 ソースから日次取得
- **arXiv 収集**: `cs.DB` / `cs.DC` / `cs.IR` を 3 秒間隔 rate limit 遵守でクロール
- **URL 正規化 + 冪等化**: UTM/トラッキングパラメータ除去後に決定論的 `article_id` 生成、配信済み履歴で重複排除 (30 日窓)
- **LLM キュレーション**: Claude Haiku 4.5 で関連度スコアリング (バッチ 10 件 + `cache_system=True`)、日本語要約、タグ付け
- **ルールベース ranker**: `final_score = llm_score * source_weight` で Top 5 ニュース + Top 2 論文を選出
- **Flex Message 配信**: LINE Messaging API Push で carousel 形式 (最大 10 bubble)
- **分析基盤連携**: `analytics-platform` JSONL に `article_collected` / `article_curated` / `digest_delivered` を emit、dbt で staging/marts 構築

**スタック**: Python 3.12 / FastAPI / aiosqlite (hot path の配信済み履歴のみ) / feedparser / arxiv / line-bot-sdk v3 / llm-client (path dep) / analytics-platform (path dep)

**ロードマップ**: Phase 1 (MVP) → Phase 1.5 (ソース拡充 + GitHub/Reddit/Qiita) → Phase 2 (LINE 上の自然言語検索 QA + sqlite-vec) → Phase 3 (ドメイン拡張 + フィードバック学習 + 動的閾値) → Phase 4 (GCP 移行、analytics-platform Phase 5+ と合流)

詳細: [`tech-news-agent/README.md`](./tech-news-agent/README.md)

---

### `driving-license-bot` — 運転免許 学科試験対策 LINE Bot (Phase 0)

車の運転免許（仮免・本免）の学科試験対策を行う LINE Bot。問題は LLM（Vertex AI 上の Gemini、設計上は将来 Claude への切替も可）で自動生成し、**根拠条文（道路交通法）・教則ページを必ず添付** することで学習者が一次ソースに到達できる導線を担保する。

> 本サービスは個人運営の学習支援ツールであり、学科試験合格を保証するものではない（公認教習所が提供するものではない）。

**主な機能 (計画)**
- **問題自動生成**: Vertex AI Gemini (Question Generator / Tutor) が学科試験形式の問題を生成。`AGENT_LLM_PROVIDER=claude` への切替も実装済（Vertex AI Marketplace で Claude が承認された環境向け）
- **品質クロスチェック**: Vertex AI Gemini (Quality Reviewer) が独立に問題品質を検証。Generator を Claude に切り替えれば Claude × Gemini の二重 LLM cross-check 構成になる
- **根拠提示**: 各問題に道路交通法の該当条文 / 教則該当ページを必ず添付
- **学習履歴管理**: Firestore（セッション・ユーザー）+ BigQuery（出題履歴・分析、`analytics-platform` と共用）
- **教材アセット**: GCS に標識画像 / 教則 PDF / 問題プールを格納
- **非同期処理**: LINE Webhook は即時 200 OK を返し、Cloud Tasks 経由で `agent-service` にディスパッチ
- **法令・教則の入手方針**: `docs/DATA_SOURCES.md` に調達方針を明記

**アーキテクチャ**

```
LINE Platform
   ↓
Cloud Run: line-bot-service (FastAPI) ─ 即時 200 OK + Cloud Tasks enqueue
   ↓
Cloud Run: agent-service (Claude Agent SDK + Vertex AI)
   │  全 MCP 呼び出し → security-platform/MCP Proxy 経由
   ├──► Vertex AI: Gemini (Question Generator / Tutor)  ※既定。AGENT_LLM_PROVIDER で Claude に切替可
   ├──► Vertex AI: Gemini (Quality Reviewer cross-check)  ※Generator を Claude にした場合に二重 LLM 構成
   ├──► Firestore (セッション・ユーザー)
   ├──► BigQuery (出題履歴・分析、analytics-platform 共用)
   └──► GCS (標識画像・教則 PDF・問題プール)
```

**スタック**: Python 3.12 / FastAPI / Claude Agent SDK / Vertex AI (Gemini 既定 / Claude 切替可) / Cloud Run / Cloud Tasks / Firestore / BigQuery / GCS / Terraform

**ステータス / ロードマップ**: Phase 0 基盤整備進行中 → Phase 1 最小デプロイ（Terraform 一発削除可）→ Phase 2 機能拡充（`docs/PHASE2_PLAN.md` に PR 分割計画）

詳細: [`driving-license-bot/README.md`](./driving-license-bot/README.md) / [`driving-license-bot/docs/DESIGN.md`](./driving-license-bot/docs/DESIGN.md)

---

### `security-platform` — エージェントセキュリティ基盤

全エージェント共通のセキュリティ監視・防御基盤。各エージェントの MCP トラフィックをプロキシ経由に集約し、脆弱性 CVE を継続監視する。

**主な機能**
- **CVE 監視**: NVD / GitHub Advisory / OSV / VulnerableMCP から脆弱性を収集し、`config/inventory.yaml` 記載のコンポーネントと照合
- **MCP Proxy (Gateway)**: 各エージェントの MCP 呼出を中継し、レート制限・ツールピニング（rug-pull 検知）・DLP・プロンプトインジェクション検出を実施
- **通知**: Slack / LINE Notify / メールで脆弱性・違反を通知
- **Dashboard**: `http://localhost:8000` で脆弱性・ツール呼出ログ・インベントリを可視化
- **Red Team**: Promptfoo による敵対的テスト

**スタック**: Python 3.12 / FastAPI / SQLite / uvicorn / Node.js (MCP scan) / Promptfoo

詳細: [`security-platform/README.md`](./security-platform/README.md)

---

### `fujisawa-platform` — 藤沢市情報の共通基盤ライブラリ

藤沢市の市役所 HP / PDF を一次ソースとする **共通基盤ライブラリ**。サービス単体では起動せず、将来開発予定の 2 エージェント (`fujisawa-info-bot` / `fujisawa-hokatsu-agent`) が `pyproject.toml` の `[tool.uv.sources]` で path dep として参照する形で利用される。**クロール / PDF 解析 / ベクトル検索 / 出典 Skill / 表記ゆれ吸収 / ETL** を一元提供する。

**主な機能**
- **Polite クロール**: `PoliteFetcher`（rate limit 遵守 / User-Agent + 連絡先明示）、`WaybackClient`（Internet Archive バックフィル）、`parse_sitemap` / `parse_feed`
- **PDF 解析**: `docling` ベースの構造化抽出（ETL Job 用 optional 依存）
- **ベクトル検索**: 開発・テスト時は `InMemoryStore`、本番は Cloud SQL (Postgres) + `pgvector` の `PgvectorStore`
- **Embedding**: `MockEmbeddingClient`（CI / 開発）/ `VertexEmbeddingClient`（本番）
- **出典 Skill**: 回答に対する一次ソース URL / 取得日時の付与
- **表記ゆれ吸収**: `FacilityResolver` による施設名の正規化（canonical name + aliases、スコア付き照合）
- **ETL 差分検知**: `compute_hash` / `has_changed` / `FreshnessMetadata` で更新検知 → 差分のみ再 embedding
- **配備**: Terraform 構成完成済 (Cloud SQL + pgvector の本番ベクトル基盤)

**消費側エージェント (今後開発予定 / 未実装)**
- **`fujisawa-info-bot`**: 藤沢市の暮らし情報を返す市民向け LINE Bot
- **`fujisawa-hokatsu-agent`**: 保育園入所活動（保活）支援エージェント

**スタック**: Python 3.12 / uv / asyncpg / pgvector / Cloud SQL (Postgres) / Vertex AI Embeddings / docling / Terraform

**ステータス**: Phase 4-2h step 3 実装済（Terraform 完成、配備可能状態）

設計詳細: [`docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](./docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) / [`fujisawa-platform/README.md`](./fujisawa-platform/README.md)

---

## 全体アーキテクチャ

```
┌──────────────────────────────────────────────────────────┐
│ User (Web / LINE)                                        │
└────────────────────────┬─────────────────────────────────┘
                         ↓
      ┌──────────────────┴──────────────────┐
      ↓                  ↓                  ↓
┌─────────────┐  ┌────────────────┐  ┌────────────────┐
│ kanie-lab-  │  │ stock-analysis-│  │ lifeplanner-   │
│ agent       │  │ agent          │  │ agent          │
│ (FastAPI)   │  │ (FastAPI)      │  │ (FastAPI)      │
└──────┬──────┘  └────────┬───────┘  └───────┬────────┘
       │  MCP tool calls  │                  │
       ↓                  ↓                  │
┌──────────────────────────────────────┐     │
│ security-platform MCP Proxy :8080    │     │
│  (rate limit / DLP / tool pinning /  │     │
│   injection detection / audit log)   │     │
└──────┬───────────────────────────────┘     │
       ↓                                     │
┌──────────────────────────────────────┐     │
│ External MCP Servers                 │     │
│  brave-search / google-search /      │     │
│  arxiv / semantic-scholar / e-Stat   │     │
│  / e-Gov-law / fetch / playwright    │     │
└──────────────────────────────────────┘     │
                                             ↓
                              ┌────────────────────────────┐
                              │ Anthropic / Vertex AI      │
                              │  (Claude Sonnet / Opus)    │
                              └────────────────────────────┘

   ┌──────────────────────────────────────┐
   │ security-platform Collector/Analyzer │ ← cron で CVE を定期取得・照合
   │ → Dashboard :8000 / Notifier         │
   └──────────────────────────────────────┘
```

---

## 共通開発ルール

| 項目 | 内容 |
|---|---|
| Python | 3.12+ |
| パッケージ管理 | uv |
| ブランチ戦略 | `feature/*` → PR → main マージ（main への直接 push 禁止） |
| LLM | Anthropic Claude (直呼 or Vertex AI)。`LLM_PROVIDER` で切替 |
| MCP | 可能な限り `security-platform` の MCP Proxy (`http://localhost:8080`) 経由 |
| シークレット | `.env` は gitignore。`.env.example` にキー一覧のみ記載 |
| セキュリティ | 新規エージェント追加時は `security-platform/config/inventory.yaml` と `scan.yaml` に登録 |
| 機能設計ドキュメント | 中規模以上の機能追加・アーキテクチャ変更は [`docs/PROPOSALS/`](./docs/PROPOSALS/) に提案 doc (KEP ベース) を作成。詳細: [`docs/PROPOSALS/README.md`](./docs/PROPOSALS/README.md) |

---

## 新規エージェント追加手順

1. `<agent-name>/` ディレクトリ作成（`pyproject.toml` / `Dockerfile` / `README.md`）
2. MCP を使う場合は `security-platform/config/inventory.yaml` の `mcp_servers` と `npm_packages` に登録
3. `security-platform/config/scan.yaml` の `targets.source_directories` / `mcp_configs` に追加
4. MCP クライアント設定で `transport: "http"` / `url: "http://localhost:8080"` を指定（プロキシ経由）
5. CVE / gitleaks / MCP config スキャンが CI で回ることを確認

詳細: [`security-platform/README.md`](./security-platform/README.md#applying-security-layers-to-an-agent-system)

---

## Claude Code 開発環境 (ECC)

本リポジトリは [ECC (Everything Claude Code)](https://github.com/affaan-m/ECC) を `--target claude-project --profile full` で `.claude/` 配下に project-level install しています。Claude Code で本 monorepo を開くと、63 agents + 249 skills + 言語別 rules / commands / hooks / MCP configs が自動的に利用可能になります。

```bash
# 新規 clone 後 or アップグレード時
scripts/setup-ecc.sh           # 初回 setup (install-state.json 再生成)
scripts/setup-ecc.sh --upgrade # upstream 最新を反映
```

- **License**: ECC は MIT licensed (`Copyright (c) 2026 Affaan Mustafa`)、`.claude/LICENSE` 同梱
- **詳細**: [`.claude/NOTICE.md`](./.claude/NOTICE.md) (出典 / 再現方法 / アップグレード手順)
- **重複インストール注意**: `~/.claude/` (user-level) で ECC を別途 install している場合、ECC docs の "Do not stack install methods" に従い user-level / project-level のどちらか一方に統一してください

---

## ライセンス

[LICENSE](./LICENSE) 参照。
