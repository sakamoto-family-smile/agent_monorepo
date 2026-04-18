# ライフプランナーエージェント (lifeplanner-agent)

Money Forward ME の家計データを起点に、家族単位のライフプランニング・長期シミュレーション・ライフイベント（出産・住宅購入・車買替等）ごとの費用増加検討を、対話型 AI エージェントで支援するシステム。

---

## 1. 目的とゴール

- **家族単位**での中長期（30〜50年）のキャッシュフロー・純資産推移を可視化する
- 出産・進学・住宅購入・車買替・転職・退職等の **ライフイベント発生時の家計影響** を定量比較する
- **日本固有の税制・社会保障制度**（所得税・住民税・社保料・児童手当・NISA/iDeCo・住宅ローン控除）を取り込む
- LINE / Web 両方から、自然言語で「車を買ったら住宅購入計画にどう影響する？」のような **What-if 問い合わせ** に答える
- 既存の `stock-analysis-agent` を投資運用シミュの入力として連携する

### ゴールでないもの

- 投資助言・税理士業務の完全代替ではない（参考値として出し、免責明記）
- リアルタイム銀行 API 連携（MVP ではやらない）
- 米国・その他国の税制（日本専用）

---

## 2. スコープと前提

| 項目 | 値 |
|---|---|
| 利用単位 | 家族（夫婦 + 子）、複数メンバー共有 |
| 地理 | 日本のみ |
| データ取得 | **Money Forward ME の CSV エクスポート手動アップロード** |
| UI | LINE Bot + Web UI の両方 |
| 税制精度 | 年度ごとに税制テーブルを更新（年版管理） |
| 実装方針 | 段階的リリース（MVP → 順次拡張） |
| 開発言語 | Python 3.12+ / FastAPI |
| エージェント基盤 | Claude Agent SDK（stock-analysis-agent と揃える） |
| インフラ | ローカル（Docker Compose）＋ GCP（本番） |

---

## 3. Money Forward ME データ取込仕様

### 3.1 エクスポート方式

MF ME（有料プレミアム）の **家計簿 → 詳細 → ダウンロード** 機能で、月別または期間指定の **CSV** を取得する。ユーザーが Web UI / LINE 経由でアップロードする。

### 3.2 想定 CSV カラム（実データで要検証）

| カラム名 | 型 | 説明 |
|---|---|---|
| 計算対象 | int | 0 = 対象外, 1 = 対象 |
| 日付 | YYYY/MM/DD | 取引日 |
| 内容 | str | 店舗名・取引内容 |
| 金額（円） | int | **支出は負、収入は正**（要実運用確認） |
| 保有金融機関 | str | 銀行・カード等 |
| 大項目 | str | MF独自分類（食費/住居/…） |
| 中項目 | str | MF独自分類（食料品/光熱費/…） |
| メモ | str | ユーザー記入 |
| 振替 | int | 0 = 通常取引, 1 = 口座間振替 |
| ID | str | MF内一意 ID |

- エンコーディング: **Shift-JIS が既定**（アップロード時に自動判定→UTF-8変換）
- 重複取込防止: `ID` カラム、または `日付+金額+内容+金融機関` のハッシュでユニーク制約

### 3.3 取込フロー

```
CSV upload → エンコード判定 → パース → バリデーション
           → 振替取引除外 → カテゴリ正規化（MF独自→自社マスタ）
           → DB 永続化（取引テーブル）→ ETL でサマリ更新
```

### 3.4 資産・負債スナップショット

取引データとは別に、以下をユーザー入力で管理:
- 現預金残高（銀行別）
- 投資資産（証券会社別・銘柄別）
- 不動産（評価額・住所・取得価額）
- ローン残高（住宅・車・その他）
- 保険契約

MF の資産情報は CSV 化されない項目もあるため、一部は手入力が必要。

---

## 4. 機能要件（フル仕様）

番号は実装優先度ではなく機能番号。優先度は §5 参照。

### F1. データ取込・正規化
- MF ME CSV アップロード（Web / LINE）
- Shift-JIS / UTF-8 自動判定
- カテゴリマッピング（MF大項目→自社カテゴリ）
- 重複取込防止
- 振替取引の自動除外
- CSV エクスポート（逆方向・バックアップ用途）

### F2. 世帯プロファイル管理
- 家族メンバー管理（名前・生年月日・属性）
- 世帯主・配偶者・子ども・扶養家族の関係
- 雇用形態・年収・勤務先
- 居住地（税率計算に使用）
- 権限管理（閲覧のみ / 編集可 / 管理者）

### F3. 現状分析（ダッシュボード）
- 月次・年次の収支サマリ
- 固定費 / 変動費 の分解
- 貯蓄率の時系列
- カテゴリ別支出トレンド
- 純資産（資産 - 負債）推移
- 異常値検出（通常月比で +3σ の支出等）

### F4. ライフイベントシミュレーション
実装するイベントカタログ:

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

各イベントは **発生時期・規模・確率（Monte Carlo用）** のパラメータを持つ。

### F5. 長期プロジェクション
- 年次キャッシュフロー（30〜50年）
- 純資産推移
- インフレ率・賃金上昇率・投資リターンを前提として切替可能
- **Monte Carlo シミュレーション**（投資リターンの分散を反映、成功確率を算出）
- シナリオ感度分析（「金利が+1%上がったら？」）

### F6. LLM 対話型アドバイス
- 「車を買うタイミングはいつが良い？」のような自然言語質問
- 複数シナリオの比較を自然言語で要約
- 改善提案（節約余地・iDeCo/NISA活用・保険見直し）
- 免責文言の自動付記

### F7. 日本税制計算（年版管理）
- 所得税（給与所得・事業所得・雑所得・譲渡所得）
- 住民税（均等割・所得割）
- 社会保険料（協会けんぽ / 組合健保 / 国保 / 厚生年金 / 国民年金）
- 所得控除（基礎・配偶者・扶養・社保・生保・iDeCo・医療費・ふるさと納税）
- 税額控除（住宅ローン・配当・外国税額）
- 公的制度（児童手当・幼保無償化・高校授業料無償化・奨学金）
- 年版データは `data/tax_tables/{year}.yaml` で管理

### F8. シナリオ管理
- シナリオの名前付き保存
- シナリオ同士の比較ビュー（年次グラフ・合計純資産・達成確率）
- ベースラインからの差分表示
- シナリオのフォーク（1クリック派生）

### F9. LINE 連携
- LIFF（LINE Front-end Framework）による認証連動
- メッセージ起点のクイック質問
- シナリオ実行結果のカード通知
- CSV アップロード受付（Messaging API の file upload）
- リマインダー（CSV 月次取込忘れ・ライフイベント時期）

### F10. Web UI
- ダッシュボード（現状分析）
- シナリオビルダー（タイムライン UI）
- プロジェクション可視化（Chart.js / Recharts）
- CSV アップロード
- 家族メンバー管理

### F11. 家族共有・権限管理
- 世帯単位のデータ分離
- ロール: `owner` / `editor` / `viewer`
- 個人プライバシー項目（個人の給与等）の表示制御
- 招待フロー（LINE/Email）

### F12. 通知・リマインダー
- 月次 CSV アップロードのリマインド
- シナリオ上のイベント発生が近い時の通知
- 税制改正・市況変化時のシミュレーション再計算提案

---

## 5. 実装フェーズ（段階的リリース）

### Phase 0: 基盤セットアップ（1週間想定）
- リポジトリ構成 / pyproject / Docker / CI
- FastAPI 骨組み
- DB スキーマ初版
- 認証基盤（Firebase Auth）
- 開発環境 Makefile

### Phase 1: MVP（現状可視化）
**目的**: MF CSV をアップロードして現状が見える
- F1 データ取込・正規化 — **実装済** (MF 大項目 → canonical カテゴリ + fixed/variable/income)
- F2 世帯プロファイル — **実装済** (members / assets / liabilities CRUD)
- F3 現状分析 — **実装済** (月次収支・canonical カテゴリ・固定費/変動費・貯蓄率・純資産・3σ異常検出)
- F10 Web UI（アップロード + ダッシュボードのみ）— 未実装
- F11 家族権限（owner のみ）— 未実装

### Phase 2: 単一シナリオシミュ
**目的**: 1 つのライフイベントで将来を動かせる
- F4 から **E01 出産 / E02 住宅 / E04 車** の3イベント
  - **E01 出産: 実装済** (出産費用・育休給付・児童手当・保育料・教育費の 5 項目)
  - E02 住宅 / E04 車: 未実装
- F5 決定論プロジェクション(Monte Carloは後回し) — **実装済** (30 年)
- F7 税制計算(給与所得+住民税+社保のみ、年版は単年) — **実装済** (2026 年版)
- F8 シナリオ保存・ベース比較 — **シナリオ保存/実行は実装済、比較は未実装**
- F10 シナリオビルダーの基本版 — 未実装

### Phase 3: LLM 対話 + LINE
**目的**: 自然言語で操作・質問できる
- F6 LLM アドバイザー（Claude Agent SDK）
- F9 LINE Bot（質問応答 + CSVアップロード）
- F8 シナリオ比較をLLMで要約

### Phase 4: 高度シミュレーション
- F4 残りのイベント（E03/E05-E12）
- F5 Monte Carlo / 感度分析
- F7 税制フル対応（年版管理）
- F11 家族共有 + 権限
- F12 通知・リマインダー
- 既存 `stock-analysis-agent` 連携（運用リターン予測を取り込む）

### Phase 5: 運用品質向上
- コスト最適化（LLM キャッシュ・モデルルーティング）
- 監査ログ・変更履歴
- E2E テスト自動化
- パフォーマンス最適化

---

## 6. 非機能要件

### 6.1 セキュリティ（最優先）
- 家計データは **PII + 機微情報**。DB 列単位の暗号化（pgcrypto）
- LLM プロンプトにフル個人情報を載せない（必要最小限＋匿名化）
- Secret Manager で認証情報管理（ハードコード禁止）
- 通信は HTTPS 必須
- 認証: Firebase Auth（LINE/Google/Email）
- 監査ログ: 誰がいつ何を見た/変えた
- **PIIをログに出力しない**（ログフィルタ必須）

### 6.2 正確性・監査性
- 税計算は単体テスト 90%+ カバレッジ
- 各シナリオ出力に「どの前提・どの計算式を使ったか」のトレースを付ける
- 年版切替時は過去結果が影響を受けないよう snapshot 方式

### 6.3 性能
- Monte Carlo 10,000 trials が 5 秒以内（目標）
- ダッシュボード初期表示 < 2 秒

### 6.4 信頼性
- テスト 80%+ カバレッジ（stock-analysis-agent と同水準）
- エラーハンドリング: CSV 形式崩れ・LLM タイムアウト・外部 API 失敗すべて明示的に

### 6.5 プライバシー・利用規約
- 家計データの削除要求に対応（GDPR 類似）
- 第三者への提供なし
- LLM プロバイダへの送信内容を利用規約に明示

---

## 7. システム構成

### 7.1 ローカル開発

```
┌──────────────────────────────────────────────┐
│ docker-compose                                │
│  ┌─────────┐  ┌──────────┐  ┌──────────────┐│
│  │ FastAPI │→ │ Postgres │  │  Redis       ││
│  │ (app)   │  │ (家計DB) │  │  (キュー/    ││
│  └─────────┘  └──────────┘  │   キャッシュ)││
│      ↓                       └──────────────┘│
│  Claude Agent SDK (直接API)                   │
│      ↓                                         │
│  Brave Search MCP (税制改正ニュース)           │
└──────────────────────────────────────────────┘
```

- ローカル LINE 連携は ngrok で Webhook 公開

### 7.2 GCP 本番構成

```
                   ┌─────────────────────┐
  LINE Messaging ─→│  API Gateway        │
  Web UI        ──→│  (Cloud Endpoints)  │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │  Cloud Run          │
                   │  (FastAPI app)      │
                   └──┬──────────────────┘
                      ├─→ Cloud SQL (Postgres) ──── 取引・世帯・シナリオ
                      ├─→ Cloud Storage ────────── CSV アップロード一時保管
                      ├─→ Secret Manager ──────── API Key / DB creds
                      ├─→ Cloud Tasks ─────────── 長時間シミュ非同期実行
                      ├─→ Cloud Scheduler ──────── 月次リマインド / 税版更新
                      ├─→ Vertex AI (Gemini) ──── 軽量な分類・要約
                      └─→ Anthropic API ────────── Claude（Agent SDK経由）

  Firebase Auth ──→ 認証・家族アカウント
  Cloud Logging / Monitoring / Error Reporting ─ 全コンポーネント
```

| GCP コンポーネント | 用途 |
|---|---|
| Cloud Run | FastAPI ホスト（stateless） |
| Cloud SQL (Postgres) | 取引・世帯・シナリオ永続化（pgcrypto で暗号化） |
| Cloud Storage | CSV 一時保管（署名付き URL） |
| Secret Manager | OAuth・API Key・DB 接続情報 |
| Cloud Tasks | Monte Carlo 等の重い計算の非同期化 |
| Cloud Scheduler | 定期リマインダー・税版更新ジョブ |
| Firebase Auth | ユーザー認証（LINE/Google） |
| Vertex AI | 軽量分類（カテゴリマッピング補助） |
| Anthropic Claude | 主要な対話・提案 |
| Cloud Logging | 全ログ集約・PIIフィルタ適用後 |
| Error Reporting | 例外の集約アラート |
| Cloud Armor / IAP | 不正アクセス防御 |

### 7.3 既存 monorepo との連携

```
agent_monorepo/
├── security-platform/          ← 認証・認可・MCP プロキシ
├── stock-analysis-agent/       ← 投資リターン予測（内部APIで呼出）
├── lifeplanner-agent/          ← 本システム
└── kanie-lab-agent/            ← 別件
```

- `security-platform` の MCP gateway 経由で Brave Search 等を共通利用
- `stock-analysis-agent` の `/api/screen` `/api/analyze` を投資シミュの入力に再利用

---

## 8. エージェント設計

### 8.1 全体構造（orchestrator + deterministic tools）

`stock-analysis-agent` と同じパターン：
- **LLM オーケストレーター** が自然言語を解釈し、決定論ツールを呼び出す
- 数値計算は Python（再現性・監査性のため LLM では計算させない）
- LLM は「結果を自然言語で要約・提案」と「質問の意図解釈」だけに使う

```
┌─────────────────────────────────────────────┐
│  LifePlannerOrchestrator (Claude Agent SDK) │
│    - 質問意図の分類                         │
│    - シナリオ構築の対話                     │
│    - 結果の自然言語要約・提案                │
└────┬────────────────────────────────────────┘
     │ tool call / function call
     ↓
┌─────────────────┬──────────────────┬────────────────┐
│ HouseholdAgent  │ SimulatorAgent   │ TaxAgent        │
│ (世帯データCRUD)│ (決定論計算)      │ (日本税制計算)   │
└─────────────────┴──────────────────┴────────────────┘
┌─────────────────┬──────────────────┬────────────────┐
│ CsvImporter     │ EventCatalog     │ AdvisorAgent    │
│ (MF CSV取込)    │ (ライフイベント) │ (LLM提案生成)   │
└─────────────────┴──────────────────┴────────────────┘
┌─────────────────────────────────────────────────────┐
│ External: stock-analysis-agent / brave-search MCP    │
└─────────────────────────────────────────────────────┘
```

### 8.2 各エージェント / モジュールの責務

| 名前 | 種別 | 責務 |
|---|---|---|
| `LifePlannerOrchestrator` | LLM Agent | ユーザー質問の意図解釈、ツール呼び出し、結果のナラティブ化 |
| `HouseholdAgent` | deterministic | 世帯・家族メンバー・資産負債の CRUD、現状分析 |
| `CsvImporter` | deterministic | MF CSV パース・正規化・重複排除 |
| `SimulatorAgent` | deterministic | 年次キャッシュフロー計算、Monte Carlo |
| `EventCatalog` | deterministic | 12種ライフイベントのパラメータ→財務影響変換 |
| `TaxAgent` | deterministic | 年版税制テーブルに基づく税額計算 |
| `AdvisorAgent` | LLM | シナリオ結果の自然言語解説・改善提案 |
| `NewsSearchTool` | MCP | 税制改正・市況の最新情報取得（brave-search） |
| `InvestmentBridge` | adapter | stock-analysis-agent API 呼出 |

### 8.3 対話フロー例

```
User (LINE): 「来年子供産まれて、3年後に家買いたいけど、車も買替時期なんだよね」
  ↓
LifePlannerOrchestrator:
  1. 意図分類: [E01 出産, E02 住宅, E04 車] の複合シナリオ
  2. HouseholdAgent から現状取得
  3. EventCatalog でそれぞれの影響を数値化
  4. SimulatorAgent で3パターン実行:
     (A) 全部実行 / (B) 車を5年遅らせ / (C) 住宅を2年遅らせ
  5. TaxAgent で税額反映
  6. AdvisorAgent で自然言語化
  ↓
Response: "3パターン比較しました。60年後純資産は A=3200万円 / B=4100万円 / C=3850万円。
          子の大学進学時(18年後)の可処分余力は B が最も高い..."
```

---

## 9. ディレクトリ構成（想定）

```
lifeplanner-agent/
├── README.md                       ← 本ドキュメント
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── .env.example
├── app/
│   ├── main.py                     ← FastAPI entrypoint
│   ├── config.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── household.py
│   │   ├── csv_importer.py
│   │   ├── simulator.py
│   │   ├── event_catalog.py
│   │   ├── tax_jp/
│   │   │   ├── __init__.py
│   │   │   ├── income_tax.py
│   │   │   ├── resident_tax.py
│   │   │   ├── social_insurance.py
│   │   │   └── credits.py
│   │   ├── advisor.py
│   │   └── investment_bridge.py    ← stock-analysis-agent連携
│   ├── models/
│   │   ├── household.py
│   │   ├── transaction.py
│   │   ├── asset.py
│   │   ├── scenario.py
│   │   └── event.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── household.py
│   │   ├── upload.py               ← CSV upload
│   │   ├── dashboard.py
│   │   ├── scenarios.py
│   │   ├── simulate.py             ← SSE streaming
│   │   ├── chat.py                 ← LLM対話
│   │   └── line_webhook.py         ← LINE Messaging
│   ├── services/
│   │   ├── database.py
│   │   ├── storage.py              ← GCS adapter
│   │   ├── auth.py                 ← Firebase
│   │   └── pii_filter.py           ← log filter
│   └── utils/
│       ├── encoding.py             ← Shift-JIS detect
│       └── money.py                ← 通貨計算 (Decimal)
├── data/
│   ├── tax_tables/
│   │   ├── 2024.yaml
│   │   ├── 2025.yaml
│   │   └── 2026.yaml
│   ├── benchmarks/
│   │   ├── education_cost.yaml     ← 幼〜大 学費平均
│   │   ├── housing_cost.yaml       ← 地域別相場
│   │   └── childcare.yaml          ← 保育料算定
│   └── category_mappings/
│       └── mf_to_canonical.yaml    ← MF大項目→自社カテゴリ
├── infra/
│   ├── terraform/                  ← GCP IaC
│   └── migrations/                 ← Alembic
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── batch/                           ← 定期ジョブ（税版チェック等）
└── frontend/                        ← Web UI（Next.js想定、Phase 1で追加）
```

---

## 10. 技術スタック

| 層 | 採用候補 | 備考 |
|---|---|---|
| 言語 | Python 3.12+ | monorepo 他エージェントと揃える |
| Web | FastAPI | 同上 |
| エージェント | Claude Agent SDK | stock-analysis-agent と揃える |
| DB | PostgreSQL 16+ | JSONB + pgcrypto |
| マイグレーション | Alembic | |
| キャッシュ | Redis | セッション・計算キャッシュ |
| 認証 | Firebase Auth | LINE Login 連携可 |
| LINE | LINE Messaging API + LIFF | |
| フロント | Next.js 14 + Chart.js or Recharts | Phase 1 後半 |
| テスト | pytest + httpx | monorepo 標準 |
| コンテナ | Docker / docker-compose → Cloud Run | |
| CI | GitHub Actions | monorepo 既存を流用 |
| IaC | Terraform | |
| LLM | Anthropic Claude (Opus/Sonnet) + Vertex AI Gemini (軽量タスク) | |

---

## 11. データモデル（ER 概要）

```
User ──< HouseholdMember >── Household
                                │
                                ├─< Transaction (MF CSV由来)
                                ├─< Asset / Liability
                                ├─< Scenario >── LifeEvent (多数)
                                └─< AuditLog
```

主要テーブル:
- `users` (id, firebase_uid, email, role)
- `households` (id, name, address, created_at)
- `household_members` (household_id, user_id, role, relation)
- `transactions` (household_id, date, amount_encrypted, category, source_id, ...)
- `assets` / `liabilities` (household_id, kind, value_encrypted, ...)
- `scenarios` (household_id, name, base_assumptions_json)
- `life_events` (scenario_id, event_type, start_year, params_json)
- `simulation_results` (scenario_id, year, metrics_json)
- `audit_logs` (actor_id, action, target, timestamp)

---

## 12. 開発着手時の次アクション

1. Phase 0 開始: `pyproject.toml` / Dockerfile / FastAPI 骨組み作成
2. DB スキーマ初版 + Alembic マイグレーション
3. CSV パーサーのプロトタイプ（実 MF エクスポートで検証）
4. `data/tax_tables/2026.yaml` を 1 ファイル用意（最低限の所得税率表）
5. Phase 1 のダッシュボード API 3 本（upload / summary / categories）

---

## 13. オープン事項・要検討

- 実 MF CSV のフォーマット（列名・エンコーディング）の実地確認
- Firebase Auth で家族メンバー招待フローの UX 設計
- LINE Bot の LIFF 統合（認証・Webhook の詳細）
- 税制テーブルのデータソース（国税庁 PDF → 手動 YAML 化 / サードパーティ API）
- Monte Carlo の計算バックエンド（Python 純 / numpy / Rust 拡張）
- フロントのデザインシステム（既存 family-infra-service と揃えるか）

---

## 14. 免責

本システムの出力は参考値であり、税務・投資・法務の正式な助言ではない。個別の重要判断は税理士・ファイナンシャルプランナー等の専門家に相談すること。
