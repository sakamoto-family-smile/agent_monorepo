# lifeplanner-agent 設計書

| | |
|---|---|
| **Version** | 1.0 |
| **最終更新** | 2026-05-07 |
| **Status** | Active |
| **Owner** | @kurama554101 |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-04-?? | 0.1 | 初版 (README に設計内容を集約) |
| 2026-05-07 | 1.0 | `docs/SYSTEM_DESIGN_TEMPLATE.md` 準拠に再構成。README から設計内容を分離 |

---

## 0. Executive Summary

Money Forward ME の家計データを起点に、家族単位で 30〜50 年のキャッシュフロー・純資産推移をシミュレーションし、ライフイベント（出産・住宅購入・車買替等）の影響を定量比較する対話型エージェント。LINE Bot + Web UI（後者は計画中）から自然言語で What-if 質問に答える。日本固有の税制・社会保障制度を組み込んでいる。

---

## 1. 目的・スコープ

### 1.1 目的

- **家族単位**での中長期 (30〜50 年) のキャッシュフロー・純資産推移を可視化する
- 出産・進学・住宅購入・車買替・転職・退職等の **ライフイベント発生時の家計影響** を定量比較する
- **日本固有の税制・社会保障制度**（所得税・住民税・社保料・児童手当・NISA/iDeCo・住宅ローン控除）を取り込む
- LINE / Web 両方から、自然言語で「車を買ったら住宅購入計画にどう影響する？」のような **What-if 問い合わせ** に答える
- 既存の `stock-analysis-agent` を投資運用シミュの入力として連携する

### 1.2 想定ユーザー

| 種別 | 内容 |
|---|---|
| 主要 | 家族 (夫婦 + 子)、世帯主 / 配偶者の双方が LINE で操作 |
| 副次 | 開発者本人 (個人プロジェクト管理者) |
| 想定外 | 不特定多数の一般ユーザー、商用 SaaS としての利用 |

### 1.3 スコープ / Non-Goals

**スコープ**:
- 利用単位: 家族（夫婦 + 子）、複数メンバー共有
- 地理: 日本のみ
- データ取得: **Money Forward ME の CSV エクスポート手動アップロード** (リアルタイム銀行 API 連携はしない)
- UI: LINE Bot + Web UI (Web UI は Phase 5 計画中)
- 税制精度: 年度ごとに税制テーブルを更新（年版管理）
- 実装方針: 段階的リリース（MVP → 順次拡張）

**Non-Goals**:
- 投資助言・税理士業務の完全代替（参考値として出し、免責明記）
- リアルタイム銀行 API 連携
- 米国・その他国の税制（日本専用）
- 商用化・他家族へのサービス提供

---

## 2. 機能要件

詳細な機能個別の設計判断は [`PROPOSALS/`](../../docs/PROPOSALS/) に切り出している。

### 2.1 機能一覧

| ID | 機能 | 状態 | Phase | Proposal |
|---|---|---|---|---|
| F1 | データ取込・正規化 (MF CSV) | ✅ 実装済 | Phase 1 | — |
| F2 | 世帯プロファイル管理 (members / assets / liabilities) | ✅ 実装済 | Phase 1 | — |
| F3 | 現状分析 (月次収支・カテゴリ・固変・純資産・3σ異常) | ✅ 実装済 | Phase 1 | — |
| F4 | ライフイベントシミュ (E01/E02/E04 の 3 種) | ✅ 実装済 | Phase 2 | — |
| F4 | 残ライフイベント (E03/E07/E08/E11/E10/E09/E12) | ⏳ 計画 | Phase 4 | 予定 |
| F5 | 決定論プロジェクション (30 年) | ✅ 実装済 | Phase 2 | [#0001](../../docs/PROPOSALS/0001-lifeplanner-cashflow-breakdown.md) (粒度向上) |
| F5 | Monte Carlo / 感度分析 | ⏳ 計画 | Phase 4 | — |
| F6 | LLM アドバイザ (Anthropic / Vertex AI / Mock) | ✅ 実装済 | Phase 3a | — |
| F7 | 日本税制計算 (2026 単年) | ✅ 実装済 | Phase 2 | — |
| F7 | 税制フル対応 (年版管理 / 譲渡所得 / iDeCo/NISA) | ⏳ 計画 | Phase 4 | — |
| F8 | シナリオ管理・比較 | ✅ 実装済 | Phase 3a | — |
| F9 | LINE Bot (webhook / コマンド / CSV ファイル / Flex / Rich menu) | ✅ 実装済 | Phase 3b | — |
| F9 | LINE 分析コマンド (`/summary` `/networth` `/anomalies`) | ✅ 実装済 | Phase 4 | — (PR #104) |
| F9 | LINE CF 表示 / イベント設定 UI / push 通知 | ⏳ 計画 | Phase 4 | LINE_ROADMAP |
| F10 | Web UI (Next.js ダッシュボード) | ❌ 未着手 | Phase 5 | — |
| F11 | 家族共有・権限管理 (role: owner/editor/viewer) | ⏳ 部分 (owner のみ) | Phase 4 | — |
| F12 | 通知・リマインダー (LINE push) | ❌ 未着手 | Phase 4 | — |

### 2.2 ライフイベントカタログ (F4 詳細)

| ID | イベント | 主要入力 | 影響計算 |
|---|---|---|---|
| E01 | 出産・育児 | 人数・時期・両親の育休方針 | 出産費用 / 育休給付 / 児童手当 / 保育料 / 教育費(幼〜大) |
| E02 | 住宅購入 | 物件価格・頭金・金利・期間・種類 | ローン返済 / 固都税 / 修繕積立 / 住宅ローン控除 |
| E03 | 住宅売却・住替 | 売却価格・新居価格 | 譲渡所得税 / 引越費用 |
| E04 | 車購入・買替 | 価格・ローン・買替周期 | 車両費 / 任意保険 / 自動車税 / 車検 / 燃料 |
| E05 | 結婚 | 結婚費用・共同生活開始 | 一時費用 / 生活費の変化 |
| E06 | 転職・独立 | 年収変化・時期・独立時の所得形態 | 手取り / 社保料 / 税額変化 |
| E07 | 子の進学 | 公立/私立、理系/文系、一人暮らし有無 | 学費 / 仕送り / 教育資金取崩 |
| E08 | 退職・年金開始 | リタイア年齢・繰上繰下 | 公的年金 / 退職金 / 取崩戦略 |
| E09 | 相続・贈与 | 受贈額・時期 | 相続税 / 基礎控除 / 運用計画への組込 |
| E10 | リフォーム | 費用・時期 | 固都税影響 / 借入有無 |
| E11 | 介護発生 | 要介護度・在宅/施設 | 介護費用 / 公的介護保険 |
| E12 | 教育投資（大学院等） | 期間・費用 | 学費 / 収入断絶 |

各イベントは **発生時期・規模・確率（Monte Carlo 用）** のパラメータを持つ。現状は年単位 (`start_year`)、月単位プロレートは Phase 4 の PR で導入予定 (LINE_ROADMAP.md 参照)。

---

## 3. 非機能要件 (NFR)

### 3.1 性能

| 項目 | 目標 |
|---|---|
| ダッシュボード初期表示 | < 2 秒 |
| LINE webhook 応答 | < 3 秒 (LINE 制約) |
| 30 年プロジェクション計算 | < 1 秒 |
| Monte Carlo 10,000 trials | < 5 秒 (Phase 4 計画) |

### 3.2 可用性

- 家族用個人プロジェクトのため **99% 程度で十分**。計画停止 OK
- Cloud Run リージョン JP (`asia-northeast1`)、min-instances=0 (cold start 許容)
- DB は Cloud SQL Postgres (Phase 4 / GCP デプロイ時)、point-in-time recovery 7 日

### 3.3 セキュリティ

- 家計データは **PII + 機微情報**。DB 列単位の暗号化 (pgcrypto、Phase 5 で本番化)
- LLM プロンプトにフル個人情報を載せない (必要最小限 + 匿名化)
- Secret Manager で認証情報管理 (ハードコード禁止)
- 通信は HTTPS 必須
- 認証: Firebase Auth (LINE/Google/Email)。LINE Bot は webhook 署名検証 + LIFF ID トークン
- 監査ログ: 誰がいつ何を見た / 変えた
- **PII をログに出力しない** (`services/pii_filter.py` でフィルタ)
- security-platform 連携: 共通の MCP gateway 経由で Brave Search 等を利用

### 3.4 コスト

- 月額予算目安: ¥3,000 程度 (個人運用、Cloud Run + Cloud SQL + Vertex AI)
- LLM 呼出: 1 conversation あたり数百円以内 (Vertex AI Claude Sonnet を想定)
- ストレージ: 取引データ + simulation_results JSON で 1 家族あたり ~10 MB / 年

### 3.5 プライバシー / データ保持

- 家計データの削除要求に対応 (GDPR 類似)
- 第三者への提供なし
- LLM プロバイダへの送信内容を利用規約に明示
- 保持期間:
  - 取引データ: 永続 (ユーザー削除要求まで)
  - LLM 会話履歴: 90 日 (今後の機能改善のため、PII フィルタ済)
  - 監査ログ: 1 年
  - GCS CSV 一時保管: 24 時間で自動削除

### 3.6 キャパシティ

- 同時ユーザー: 家族 5 人程度想定 (Cloud Run min/max=0/2 instance で十分)
- DB レコード: 取引 ~10 万件 / 家族 / 10 年想定
- シナリオ数: 1 家族あたり ~10 シナリオ想定

### 3.7 保守性 / テスト性

- カバレッジ目標: **全体 80%+** (`stock-analysis-agent` と同水準)
- 税計算は **単体テスト 90%+** (正確性が事業価値に直結)
- 各シナリオ出力に「どの前提・どの計算式を使ったか」のトレースを付ける (audit log)
- 年版切替時は過去結果が影響を受けないよう **snapshot 方式**
- lint: `ruff check` を CI で実行
- observability: `analytics-platform` 連携で `business_event` / `llm_call` / `error_event` を JSONL 出力 (詳細は [README §0.10](../README.md))

---

## 4. データモデル

### 4.1 ER 概要

```
User ──< HouseholdMember >── Household
                                │
                                ├─< Transaction (MF CSV由来)
                                ├─< Asset / Liability
                                ├─< Scenario >── LifeEvent (多数)
                                │              └─ SimulationResult (年次)
                                ├─< LineUserLink (LINE userId 紐付け)
                                └─< AuditLog
```

### 4.2 主要テーブル

| テーブル | 用途 | 備考 |
|---|---|---|
| `users` | Firebase 認証ユーザー | `firebase_uid`, `email`, `role` |
| `households` | 世帯 (家族単位) | `id`, `name`, `address` |
| `household_members` | 世帯メンバー | `household_id`, `user_id`, `role`, `relation` |
| `transactions` | MF CSV 由来の取引 | 暗号化対象、`canonical_category` でカテゴリ正規化済 |
| `assets` / `liabilities` | 資産・負債スナップショット | 種別 (cash / deposit / investment / real_estate / mortgage 等) |
| `scenarios` | シナリオ | `base_assumptions` (JSON) で前提値を保持 |
| `life_events` | シナリオ内のライフイベント | `event_type` (E01-E12), `start_year`, `params` (JSON) |
| `simulation_results` | 年次シミュレーション結果 | `metrics` (JSON、`expense_breakdown` / `event_breakdown` 含む、PR #103) |
| `line_user_links` | LINE userId と household_id の紐付け | 1 LINE ユーザー → 1 世帯 |
| `audit_logs` | 監査ログ | `actor_id`, `action`, `target`, `timestamp` |

詳細 DDL は `infra/migrations/` (Alembic) を参照。

### 4.3 Money Forward ME データ取込仕様

#### エクスポート方式

MF ME (有料プレミアム) の **家計簿 → 詳細 → ダウンロード** で月別または期間指定の **CSV** を取得し、ユーザーが Web UI / LINE 経由でアップロードする。

#### 想定 CSV カラム

| カラム名 | 型 | 説明 |
|---|---|---|
| 計算対象 | int | 0 = 対象外, 1 = 対象 |
| 日付 | YYYY/MM/DD | 取引日 |
| 内容 | str | 店舗名・取引内容 |
| 金額（円） | int | **支出は負、収入は正** |
| 保有金融機関 | str | 銀行・カード等 |
| 大項目 | str | MF 独自分類 (食費 / 住居 / …) |
| 中項目 | str | MF 独自分類 (食料品 / 光熱費 / …) |
| メモ | str | ユーザー記入 |
| 振替 | int | 0 = 通常取引, 1 = 口座間振替 |
| ID | str | MF 内一意 ID |

- エンコーディング: **Shift-JIS が既定** (アップロード時に自動判定 → UTF-8 変換)
- 重複取込防止: `ID` カラム、または `日付+金額+内容+金融機関` のハッシュでユニーク制約

#### 取込フロー

```
CSV upload → エンコード判定 → パース → バリデーション
           → 振替取引除外 → カテゴリ正規化 (MF 独自 → canonical)
           → DB 永続化 (transactions) → サマリ更新
```

#### 資産・負債スナップショット

取引データとは別に、ユーザー入力で管理:
- 現預金残高（銀行別）
- 投資資産（証券会社別・銘柄別）
- 不動産（評価額・住所・取得価額）
- ローン残高（住宅・車・その他）
- 保険契約

MF の資産情報は CSV 化されない項目もあるため、一部は手入力が必要。

---

## 5. アーキテクチャ

### 5.1 コンポーネント構成

#### ローカル開発

```
┌──────────────────────────────────────────────┐
│ docker-compose                                │
│  ┌─────────┐  ┌──────────┐  ┌──────────────┐│
│  │ FastAPI │→ │ Postgres │  │  (Redis 計画)││
│  │ (app)   │  │ (家計DB) │  │  (Phase 5)    ││
│  └─────────┘  └──────────┘  └──────────────┘│
│      ↓                                         │
│  Anthropic SDK / Vertex AI                     │
│      ↓                                         │
│  Brave Search MCP (税制改正ニュース、計画)      │
└──────────────────────────────────────────────┘
```

ローカル DB は SQLite (`sqlite+aiosqlite:///`) でも動作 (`db_auto_create=true` で起動時自動初期化)。LINE 連携は ngrok で Webhook 公開。

#### GCP 本番構成 (Phase 4 で整備予定)

```
                   ┌─────────────────────┐
  LINE Messaging ─→│  Cloud Run          │
  Web UI        ──→│  (FastAPI app)      │
                   └──┬──────────────────┘
                      ├─→ Cloud SQL (Postgres) ──── 取引・世帯・シナリオ
                      ├─→ Cloud Storage ────────── CSV 一時保管 (24h 自動削除)
                      ├─→ Secret Manager ──────── API Key / DB creds
                      ├─→ Cloud Tasks ─────────── (Phase 4) Monte Carlo 非同期
                      ├─→ Cloud Scheduler ──────── (Phase 4) 月次リマインド
                      ├─→ Vertex AI (Claude / Gemini) ─── LLM
                      └─→ Anthropic API ────────── Claude (LLM_PROVIDER 切替)

  Firebase Auth ──→ 認証・家族アカウント
  Cloud Logging / Monitoring / Error Reporting ─ 全コンポーネント
```

### 5.2 主要モジュール

`stock-analysis-agent` と同じパターン: **LLM オーケストレーター が自然言語を解釈し、決定論ツールを呼び出す**。数値計算は Python (再現性・監査性のため LLM では計算させない)。LLM は「結果を自然言語で要約・提案」と「質問の意図解釈」だけに使う。

| モジュール | 種別 | 責務 |
|---|---|---|
| `LifePlannerOrchestrator` (`agents/orchestrator.py`) | LLM Agent | ユーザー質問の意図解釈、ツール呼び出し、ナラティブ化 |
| `HouseholdAgent` (`agents/household.py`) | deterministic | 世帯・家族メンバー・資産負債の CRUD、現状分析 |
| `CsvImporter` (`agents/csv_importer.py`) | deterministic | MF CSV パース・正規化・重複排除 |
| `SimulatorAgent` (`agents/simulator.py`) | deterministic | 年次キャッシュフロー計算、Monte Carlo (Phase 4) |
| `EventCatalog` (`agents/event_catalog/`) | deterministic | 12 種ライフイベントのパラメータ → 財務影響変換 |
| `TaxAgent` (`agents/tax_jp/`) | deterministic | 年版税制テーブルに基づく税額計算 |
| `AdvisorAgent` (`agents/advisor.py`) | LLM | シナリオ結果の自然言語解説・改善提案 |
| `InvestmentBridge` (将来) | adapter | stock-analysis-agent API 呼出 |

#### 対話フロー例

```
User (LINE): 「来年子供産まれて、3年後に家買いたいけど、車も買替時期なんだよね」
  ↓
LifePlannerOrchestrator:
  1. 意図分類: [E01 出産, E02 住宅, E04 車] の複合シナリオ
  2. HouseholdAgent から現状取得
  3. EventCatalog でそれぞれの影響を数値化
  4. SimulatorAgent で 3 パターン実行:
     (A) 全部実行 / (B) 車を 5 年遅らせ / (C) 住宅を 2 年遅らせ
  5. TaxAgent で税額反映
  6. AdvisorAgent で自然言語化
  ↓
Response: "3 パターン比較しました。30 年後純資産は A=3,200万円 / B=4,100万円 / C=3,850万円。
          子の大学進学時 (18 年後) の可処分余力は B が最も高い..."
```

### 5.3 外部依存

| 連携先 | 用途 | 認証方式 |
|---|---|---|
| LINE Messaging API | webhook / push / file upload | Channel Access Token (Secret Manager) |
| LINE Login (LIFF) | Web UI 認証 | ID トークン (`aud` 検証) |
| Anthropic API | LLM (`LLM_PROVIDER=anthropic`) | API Key |
| Vertex AI | LLM (`LLM_PROVIDER=vertex`) | ADC / SA `roles/aiplatform.user` |
| Money Forward ME | 家計データ source | (CSV 手動エクスポート、API 連携なし) |
| `analytics-platform` (path dep) | 業務ログ集約 (JSONL) | path dep |
| `security-platform` MCP gateway | Brave Search 等 (将来) | path dep |
| `stock-analysis-agent` (将来) | 投資リターン予測 | 内部 API |

### 5.4 ディレクトリ構成

```
lifeplanner-agent/
├── README.md                       ← Quickstart + API + 環境変数
├── docs/
│   ├── DESIGN.md                   ← 本ドキュメント
│   ├── LINE_ROADMAP.md             ← Phase 4 LINE 拡充の中粒度 roadmap
│   └── (future: DEPLOY.md / BACKUP_RESTORE.md)
├── pyproject.toml / Dockerfile / docker-compose.yml / Makefile / .env.example
├── app/
│   ├── main.py                     ← FastAPI entrypoint
│   ├── config.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── csv_importer.py
│   │   ├── simulator.py
│   │   ├── event_catalog/          ← E01/E02/E04 + benchmarks
│   │   ├── tax_jp/                 ← 所得税 / 住民税 / 社保 / 控除
│   │   └── (advisor / investment_bridge は将来)
│   ├── models/db.py                ← SQLAlchemy
│   ├── repositories/               ← household / transaction / scenario / line_link / profile
│   ├── routes/                     ← upload / transactions / summary / networth / anomalies / scenarios / simulate / chat / line / liff
│   ├── services/                   ← database / category_mapper / line_client / line_handler / line_flex / line_period / llm_client / summary / networth / anomalies / scenario_comparer / scenario_runner / expense_baseline / auth / line_id_token
│   ├── instrumentation/            ← analytics-platform 連携
│   └── utils/
├── data/
│   ├── tax_tables/{year}.yaml      ← 税制年版
│   ├── benchmarks/                 ← 教育費 / 住居費 / 保育料
│   ├── category_mappings/          ← MF 大項目 → canonical
│   ├── seeds/                      ← scripts/seed_events.py の入力 (PR #103)
│   └── analytics/                  ← JSONL (gitignore)
├── infra/
│   ├── terraform/                  ← (Phase 4 で整備予定、未着手)
│   └── migrations/                 ← Alembic
├── scripts/
│   ├── seed_events.py              ← JSON → DB 一括投入 (PR #103)
│   ├── setup_rich_menu.py          ← LINE Rich Menu 登録
│   └── integration_check_observability.py
├── tests/                          ← unit / integration、337 件 PASS
└── batch/                           ← 定期ジョブ (将来)
```

### 5.5 技術スタック

| 層 | 採用 | 備考 |
|---|---|---|
| 言語 | Python 3.12+ | monorepo 共通 |
| Web | FastAPI | monorepo 共通 |
| DB (本番) | PostgreSQL 16+ | JSONB + pgcrypto (将来) |
| DB (開発) | SQLite + aiosqlite | `db_auto_create=true` で初期化 |
| マイグレーション | Alembic | |
| 認証 | Firebase Auth + DEV_HOUSEHOLD_ID | LINE Login 連携 |
| LINE | line-bot-sdk v3 | LIFF + Messaging API |
| フロント | Next.js 14 + Recharts (計画) | Phase 5 |
| テスト | pytest + httpx | 337 件 (2026-05) |
| コンテナ | Docker / docker-compose → Cloud Run | |
| CI | GitHub Actions | monorepo 共通 |
| LLM | Anthropic Claude / Vertex AI | `LLM_PROVIDER` で切替 |

---

## 6. 開発フェーズ / Roadmap

### 6.1 Phase 一覧

| Phase | 名前 | 状態 | 主要内容 |
|---|---|---|---|
| Phase 0 | 基盤セットアップ | ✅ 完了 | リポジトリ / FastAPI / DB / 認証 |
| Phase 1 | MVP (現状可視化) | ✅ 完了 | F1 / F2 / F3 |
| Phase 2 | 単一シナリオシミュ | ✅ 完了 | F4 (E01/E02/E04) / F5 / F7 / F8 |
| Phase 3a | LLM アドバイザ | ✅ 完了 | F6 / F8 |
| Phase 3b | LINE 連携 | ✅ 完了 | F9 / LIFF / Flex / Rich menu |
| Phase 4 | 高度シミュ + LINE 拡充 | ⏳ 進行中 | 詳細は [LINE_ROADMAP.md](LINE_ROADMAP.md) |
| Phase 5 | 運用品質向上 | 📋 計画 | LLM キャッシュ / 監査ログ / E2E / Web UI (F10) |

### 6.2 Phase 4 の詳細

中粒度 roadmap は [`LINE_ROADMAP.md`](LINE_ROADMAP.md) に集約。サマリ:

- ✅ PR #103 — バックエンド粒度向上 (カテゴリ別 / イベント明細)
- ✅ PR #104 — LINE 分析コマンド (`/summary` `/networth` `/anomalies`)
- ⏳ PR #108 (本 PR) — 設計ドキュメントの再構成
- ⏳ PR (未番号) — LINE CF 表示 (`/cashflow <id>`)
- ⏳ PR (未番号) — LINE イベント設定 UI + `start_month` プロレート
- ⏳ PR (未番号) — 残ライフイベント (E07 子の進学 / E08 退職など)
- ⏳ PR (未番号) — GCP インフラ Terraform 整備

その他 Phase 4 全体の残:
- F5 Monte Carlo / 感度分析
- F7 税制フル対応 (年版管理 / 譲渡所得 / iDeCo/NISA)
- F11 家族共有 + 権限
- F12 通知・リマインダー (LINE push)
- 既存 `stock-analysis-agent` 連携

### 6.3 オープン事項・要検討

- 実 MF CSV のフォーマット（列名・エンコーディング）の実地確認
- Firebase Auth で家族メンバー招待フローの UX 設計
- 税制テーブルのデータソース（国税庁 PDF → 手動 YAML 化 / サードパーティ API）
- Monte Carlo の計算バックエンド（Python 純 / numpy / Rust 拡張）
- フロントのデザインシステム

---

## 7. 設計判断ログ (ADR-lite)

| 日付 | 判断 | 理由 | 詳細 |
|---|---|---|---|
| 2026-04 | LLM_PROVIDER で Anthropic 直 / Vertex AI を切替 | GCP 本番では IAM / VPC / 監査ログを統合したいが、開発時は Anthropic 直で素早く回したい | README §0.6 |
| 2026-04 | DB 初期化は `DB_AUTO_CREATE` で切替 (dev=true / prod=false) | dev / SQLite では手間を省く、prod / Postgres は alembic で厳格に | README §0.2 |
| 2026-04 | LLM_MOCK_MODE で外部 API 不要モードを提供 | テスト / オフライン開発で確定的応答が必要 | `services/llm_client.py` |
| 2026-05 | 取引データの canonical カテゴリ正規化 (MF 大項目 → 自社マスタ) | 将来の MF 仕様変更に対する耐性 + シミュレーターでのカテゴリ別計算 | `data/category_mappings/mf_to_canonical.yaml` |
| 2026-05 | YearRow に expense_breakdown / event_breakdown を追加 (旧構造維持) | UI でカテゴリ・イベント明細を表示するため。既存呼出側を破壊しないよう追加のみ | [PROPOSAL #0001](../../docs/PROPOSALS/0001-lifeplanner-cashflow-breakdown.md) |
| 2026-05 | LINE 分析コマンドは Flex Message + text fallback | SDK バージョン差異・JSON 構造エラーに耐えるため | (PR #104) |
| 2026-05 | Rich Menu を 3 ボタン (843px) → 6 ボタン (1686px) に拡張 | PR 2 で /summary /networth /anomalies を追加、画面領域確保のため | (PR #104) |
| 2026-05 | start_year は年単位、月単位プロレートは Phase 4 で導入 | Phase 2 のスコープを絞るため、購入月の精度より 30 年合計の正確性を優先 | LINE_ROADMAP.md |

---

## 8. 運用

詳細手順は別ドキュメントに切り出し予定:

- デプロイ (GCP): `docs/DEPLOY.md` (Phase 4 で整備)
- バックアップ / リストア: `docs/BACKUP_RESTORE.md` (Phase 4 で整備、`piyolog-analytics/docs/BACKUP_RESTORE.md` 参考)
- LINE Bot / LIFF / Rich menu セットアップ: [README §0.7-0.9](../README.md)
- analytics-platform 送信: [README §0.10](../README.md)

### 8.1 ローカル運用

- `make run` で起動、http://127.0.0.1:8001
- `make test` / `make lint` / `make check`
- LINE 連携は ngrok で Webhook 公開
- LLM はデフォルト `LLM_MOCK_MODE=true` (offline OK)

### 8.2 モニタリング

- `analytics-platform` JSONL → DuckDB / dbt で集計可能 (詳細は [README §0.10](../README.md))
- Cloud Logging (本番、Phase 4 以降): `[upload] cycle: uploaded=N` で正常確認
- Phoenix / Langfuse OTLP は `OTEL_EXPORTER_OTLP_ENDPOINT` 設定時のみ有効

---

## 9. セキュリティ・プライバシー

### 9.1 データ分類

| 種類 | 例 | 取扱い |
|---|---|---|
| **PII** | LINE userId / 取引明細 / 銀行口座名 | DB のみ、log には sha256 hash で記録 |
| **機微情報** | 家計収支・資産額・住所 | DB 列単位暗号化 (pgcrypto、Phase 5) |
| **機密** | LINE channel secret / DB password / Anthropic API key | Secret Manager (本番)、`.env` (gitignore) |
| **公開可** | docs / README / 設計判断 | — |

### 9.2 認証・認可

- **Web UI**: Firebase Auth (LINE/Google/Email)、`X-Household-ID` ヘッダで世帯指定
- **LINE Bot**: webhook 署名検証 (LINE channel secret)、世帯自動連携 (初回 LINE userId → household_id 紐付け)
- **LIFF**: ID トークン検証 (`aud` = LINE Login Channel ID)
- **DEV モード**: `DEV_HOUSEHOLD_ID` を fallback として使用 (本番は disable)

### 9.3 既知のリスク・残課題

- DB 列単位暗号化 (pgcrypto) は本番化していない (Phase 5)
- 監査ログ (audit_logs) は schema のみ、書込 / 表示は未実装 (Phase 5)
- LLM プロンプトに income / 取引明細を渡しているが、PII フィルタは未実装 (Phase 4)

---

## 10. テスト戦略

| レイヤ | 対象 | カバレッジ目標 | 現状 |
|---|---|---|---|
| Unit | 純関数 / dataclass / utility (e.g., `agents/event_catalog/`, `services/expense_baseline.py`, `services/line_period.py`) | 90% | 達成 |
| Integration | route / repository / service 間連携 (e.g., `tests/test_scenarios_api.py`, `tests/test_line_handler_analysis.py`) | 80% | 達成 |
| E2E | LINE webhook → DB → reply の通し | 主要シナリオのみ | 達成 (`tests/test_line_webhook.py` + `test_line_handler_analysis.py`) |
| Tax | 単体テスト (所得税 / 住民税 / 社保) | 90% | 達成 |

合計 337 tests PASS (2026-05-07 時点)。

CI は `make check` (lint + test) を pre-merge で実行。手動 QA は LINE 実機での動作確認。

---

## 11. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 主要 API / 環境変数 / LINE Bot セットアップ / analytics-platform 連携
- [`LINE_ROADMAP.md`](LINE_ROADMAP.md) — Phase 4 LINE 拡充の中粒度 roadmap (PR 単位の詳細計画)
- [`../../docs/PROPOSALS/`](../../docs/PROPOSALS/) — モノレポ共通の機能個別提案 (ADR 兼用)
  - [`0001-lifeplanner-cashflow-breakdown.md`](../../docs/PROPOSALS/0001-lifeplanner-cashflow-breakdown.md) — PR #103 のバックエンド粒度向上 ADR

---

## 12. 用語集

| 用語 | 意味 |
|---|---|
| household_id | 1 家族を束ねる ID。複数 LINE userId を集約する単位 |
| canonical category | MF 大項目を自社マスタに正規化したカテゴリ (food / housing / utilities など 21 種) |
| YearRow | `agents/simulator.py` のシミュレーション結果 1 年分。`expense_breakdown` / `event_breakdown` を含む (PR #103) |
| CashFlowDelta | ライフイベントが特定年に発生させる金額差分 1 行。catalog 関数の戻り値型 |
| LIFF | LINE Front-end Framework。LINE 内で開く Web ページ + ID トークン取得 |
| Flex Message | LINE のリッチカードフォーマット。bubble / carousel / box / text 等 |
| Rich Menu | LINE トーク画面下部の常駐メニュー。本エージェントは 3x2 = 6 ボタン構成 |

---

## 14. 免責

本システムの出力は参考値であり、税務・投資・法務の正式な助言ではない。個別の重要判断は税理士・ファイナンシャルプランナー等の専門家に相談すること。
