# PROPOSAL-0004: 藤沢市情報 LINE Bot エージェント (`fujisawa-info-bot`)

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-09 |
| **Updated** | 2026-05-09 |
| **Target** | fujisawa-info-bot (新規エージェント) |
| **Related PRs** | (none yet) |
| **Depends on** | [PROPOSAL-0003 fujisawa-platform 共通基盤](0003-fujisawa-platform-shared-base.md) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

藤沢市公式 HP を一次ソースとし、自然言語の質問に **出典 URL 付き** で回答する LINE Bot を新規構築する。
カテゴリメニュー (防災 / 子育て / ゴミ / 手続き等) からの絞り込み、緊急情報のプッシュ配信、
やさしい日本語 / 英語対応を提供。

技術スタックは LangGraph Supervisor + 4 サブエージェント、`fujisawa-platform` (proposal 0003)
を path dep で参照することでクロール / 知識ベース / 出典 Skill を共通化。LLM は
**Vertex AI Gemini** を default、Anthropic Claude は fallback。

## 2. Motivation

### 現状の課題

- 藤沢市公式 HP は情報量が多く (sitemap.xml で 1,100+ URL)、市民が「ゴミの日いつ？」「保育園の申込どうやる？」などの素朴な疑問を解決するためにサイト内検索を駆使する必要がある
- 公式コンタクトセンターに電話で問い合わせるしかない時間外の質問
- 災害・気象警報の通知が市の Web サイト訪問依存 (能動的な push が無い)
- 高齢者・外国人住民にとって市 HP の情報は読みづらい

### 放置するとどうなるか

- 個人プロジェクトとして藤沢市民の生活 QoL を上げる機会を逃す
- 共通基盤 `fujisawa-platform` の利用例が保活 1 個だけになり、汎用性 / 共通化のメリットが薄れる
- 市 HP の改訂や緊急情報の確認を手動で行う運用が続く

### 2.1 Goals

- [ ] LINE Bot 友だち追加 → カテゴリメニュー (防災 / 子育て / ゴミ / 手続き / 観光 / 市政情報 / その他) から絞り込みで質問可能
- [ ] 自由文質問に対し RAG で公式 HP の情報を検索し、**出典 URL 付き**で回答
- [ ] **リンク先 1 階層追跡**: 該当ページに記載されているリンク (PDF / 関連ページ) も読み込んで詳細回答
- [ ] **緊急情報プッシュ**: 緊急情報 RSS の更新を 5 分間隔で poll、新規アイテムを **opt-in 友だちに** broadcast
- [ ] 多言語対応: やさしい日本語 / 英語は `tsutaeru.cloud` 経由の市公式翻訳ページに **誘導**
- [ ] 👍 / 👎 フィードバック収集で回答品質を蓄積
- [ ] 月間 1 万メッセージ想定で **コスト ¥3,000 以下/月** (LLM + GCP)

### 2.2 Non-Goals

- 保活相談 (proposal 0005 の保活エージェントへ別 LINE Channel で誘導)
- 行政手続きの代行 (申請書記入支援 / 電子申請の代理) — 案内のみ
- 多言語回答の自動生成 (LLM 経由で「やさしい日本語に変換して」は精度不安 → tsutaeru.cloud 誘導)
- 位置情報 GIS の自前構築 (「最寄りの避難所」は公式キュンマップへリンク誘導)
- 個別自治体の比較 / 全国レベルの情報 (藤沢市内のみ)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: 子育て中の母親「ゴミの日いつ？」

> 藤沢市民の田中さんが LINE で「鵠沼地区のゴミの日教えて」と送ると、Bot が
> 公式の地区別ゴミ収集カレンダー PDF を参照し、「鵠沼地区は燃えるゴミが
> 月・木、プラ容器が水曜です」と回答。フッターに公式 HP リンクと「最終確認: 2026-05-09」を付与。
> 田中さんが 👍 ボタンを押すとフィードバックが蓄積される。

#### 3.1.2 ストーリー 2: 高齢者「台風きたらどこ避難するの？」

> 70 代の山田さんが「最寄りの避難所どこ？」と LINE で送ると、Bot が
> 「公式の避難所マップで確認できます」と藤沢市公式キュンマップへ誘導。
> 「やさしい日本語で説明してほしい」と返すと、tsutaeru.cloud の市公式翻訳ページの
> 該当 URL を Flex Message で提示する。

#### 3.1.3 ストーリー 3: 緊急情報プッシュ

> 大雨警報が発令され、藤沢市公式 HP の緊急情報 RSS が更新されると、5 分以内に
> Bot が opt-in 友だちに「[緊急] 大雨警報発令、〇〇地区は避難準備中」と push。
> RSS の出典リンクと「公式 HP で最新情報を確認」フッターを必ず付与。

### 3.2 Notes / Constraints / Caveats

調査結果 ([`notes/fujisawa-platform-investigation-2026-05-09.md`](notes/fujisawa-platform-investigation-2026-05-09.md)) からの前提:

- **クロール起点は `sitemap.xml` (1,100+ URL)** を採用 (送信仕様の `sitemap.html` 案は人間用で網羅性低い)
- **緊急情報 RSS は実在**するため、Phase 4 の入力源として確定 (自前 scrape 不要)
- **多言語は tsutaeru.cloud (市公式) に誘導**: 自前で「やさしい日本語変換」を LLM で書くと精度不安
- **クロール頻度は週次** (深夜帯)、ただし緊急情報 RSS は **5 分間隔** で poll
- **コスト試算**: Gemini 2.0 Flash を Sub-agent default、Gemini 2.5 Pro を Supervisor (複雑質問のみ) で月 ¥2,000-3,000
- **リンク先 1 階層追跡** は **page count cap (1 質問あたり最大 5 URL fetch、合計 100 KB)** で過剰負荷を防ぐ
- **位置情報 UI** は LINE のリッチメニュー「現在地を送る」ボタンで明示取得
- **opt-in / opt-out** は LINE 友だち単位でリッチメニューから設定 (緊急情報 push は default OFF、ユーザーが ON する)

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 緊急情報の誤通知 (誤 push / 重複 push) | High | RSS の `<guid>` で重複検知、DLQ で再試行制限、初回は dry-run mode で 1 週間観察 |
| プロンプトインジェクションによる不正回答 | High | 入力 sanitization + Model Armor (security-platform proxy 経由)、出力に「公式 HP で最新情報を」フッター強制 |
| クロール時の鯖負荷 (city.fujisawa.kanagawa.jp 側) | Medium | `fujisawa-platform/crawler` の polite mode (1 URL/3 秒) を厳守、深夜帯バッチ |
| LLM コストの暴騰 | Medium | Gemini Flash を default、Pro は Supervisor のみ、prompt cache 活用、月次予算 alarm |
| LINE 3 秒タイムアウト | Medium | Webhook 即 200 → Pub/Sub 経由で非同期処理、Loading Indicator + Push パターン |
| **コールドスタートで Webhook が 3 秒超える** | Medium | min=0 のため初回呼出で 1-3 秒遅延あり。Webhook handler を最小化 (重い import を避け署名検証 + Pub/Sub publish のみ)、Cloud Run の Startup CPU Boost を ON、災害時のみ min=1 を env 切替で許可 |
| 災害時のスパイク (1 万 push を一度に投げる) | Medium | LINE Multicast API で 500 人/呼出、Cloud Tasks で rate limit |
| 出典なし回答の混入 | High | RAG で取れた `source_url` が空なら「お答えできません、公式 HP をご確認ください」へフォールバック |
| 利用規約違反の指摘 | Low | UA に連絡先明示、Pre-launch checklist で広報課への一報 |
| ハルシネーション (架空の制度を回答) | High | 全回答に出典 URL 強制、citation_format Skill で違反時は再生成 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
                     ┌────────────────────────┐
                     │ LINE Platform          │
                     └───────────┬────────────┘
                                 │ Webhook (HTTPS)
                                 ▼
                    ┌─────────────────────────────────┐
                    │ Cloud Run: api (FastAPI)        │
                    │  - 署名検証 / event 振り分け     │
                    │  - 即 200 + Pub/Sub             │
                    └────────────┬────────────────────┘
                                 │ Pub/Sub
                                 ▼
                    ┌─────────────────────────────────┐
                    │ Cloud Run: agent-core           │
                    │ (LangGraph Supervisor)          │
                    │                                 │
                    │  ┌──────────┐ ┌──────────┐    │
                    │  │ Intent   │ │ RAG      │    │
                    │  │ Agent    │ │ Agent    │    │
                    │  └──────────┘ └──────────┘    │
                    │  ┌──────────┐ ┌──────────┐    │
                    │  │ Crawl    │ │ Emergency│    │
                    │  │ Agent    │ │ Agent    │    │
                    │  └──────────┘ └──────────┘    │
                    └────────────┬───────┬───────────┘
                                 │       │
              ┌──────────────────┘       └──────────────────┐
              ▼                                              ▼
   ┌─────────────────────────┐                  ┌──────────────────────┐
   │ fujisawa-platform        │                  │ Firestore (session,  │
   │  - knowledge_base/       │                  │  feedback, opt-in)   │
   │  - crawler/              │                  └──────────────────────┘
   │  - pdf_pipeline/         │
   │  - skills/               │
   │  (path dep)              │
   └────────────┬─────────────┘
                │
                ▼
   ┌──────────────────────────────────────────┐
   │ Cloud SQL fujisawa_kb_db (pgvector)      │
   │  - pages (sitemap クロール結果)           │
   │  - pdf_documents                         │
   └──────────────────────────────────────────┘

   バッチ層:
   - Cloud Scheduler ──▶ Cloud Run Jobs (週次フルクロール)
                       └─▶ pgvector index 更新
   - Cloud Scheduler ──▶ Cloud Run Jobs (5 分間隔 RSS poll)
                       └─▶ 新着検知 → Cloud Tasks → LINE Multicast

   観測:
   - analytics-platform (path dep) で全 agent / MCP 計装
   - Phoenix (ローカル) / Langfuse on GKE (本番) ← optional
```

### 4.2 データモデル

ユーザー固有データは Firestore (Native mode):

```
users/{lineUserId}
  ├ profile         # display_name (LINE), area (任意、鵠沼/辻堂等)
  ├ opt_in
  │   ├ emergency_push: bool      # 緊急情報 push 受信
  │   └ language: "ja" | "ja-easy" | "en"
  ├ feedback/{messageId}
  │   ├ thumb: "up" | "down"
  │   ├ original_question: str
  │   └ created_at: timestamp
  └ sessions/{id}   # 会話履歴 (30 日 TTL)
```

### 4.3 主要モジュール

```
fujisawa-info-bot/
├── pyproject.toml             # uv project、fujisawa-platform を path dep
├── README.md                  # README_TEMPLATE 準拠
├── docs/
│   └── DESIGN.md              # SYSTEM_DESIGN_TEMPLATE 準拠
├── app/
│   ├── main.py                # FastAPI entrypoint
│   ├── line_handler.py        # 署名検証 / event 振り分け
│   ├── graph/
│   │   ├── supervisor.py      # LangGraph Supervisor
│   │   ├── state.py           # InfoBotState (TypedDict)
│   │   └── agents/
│   │       ├── intent.py      # 意図分類 (RAG / Crawl / Emergency)
│   │       ├── rag.py         # fujisawa-platform.knowledge_base 経由
│   │       ├── crawl.py       # 動的 fetch + リンク 1 階層追跡 (cap 5 URL)
│   │       └── emergency.py   # 緊急情報整理
│   ├── skills/                # info-bot 専用 Skill
│   │   ├── category_routing.md   # 7 カテゴリ → 検索範囲のマッピング
│   │   ├── flex_message.md       # LINE Flex Message テンプレ
│   │   └── feedback_response.md  # 👍👎 への返事
│   ├── tools/                 # MCP client (今回は MCP Gateway 経由を想定)
│   ├── batch/
│   │   ├── crawl_weekly.py    # 週次フルクロール job
│   │   └── poll_rss.py        # 緊急情報 RSS 5 分間隔 job
│   └── tests/
└── Makefile
```

### 4.4 LangGraph State

```python
class InfoBotState(TypedDict):
    user_id: str
    messages: list[BaseMessage]
    intent: Literal["category", "rag", "crawl", "emergency", "feedback", "settings"]
    category: str | None              # 防災 / 子育て / ゴミ / etc.
    user_profile: UserProfile | None
    rag_results: list[RAGResult]      # fujisawa-platform.knowledge_base から
    crawl_pages: list[FetchedPage]    # Crawl Agent が動的 fetch
    final_response: FlexMessage | TextMessage
```

### 4.5 LLM ルーティング

コスト最適化のため Gemini を default、Anthropic は fallback:

| 役割 | モデル | 用途 |
|---|---|---|
| Supervisor (意図分類 / 最終整形) | **Gemini 2.5 Pro** (or 2.0 Pro) | 複雑な質問のみ |
| 意図分類 (素朴な質問) | **Gemini 2.0 Flash** | "ゴミの日" 等の単純質問 |
| RAG Agent | **Gemini 2.0 Flash** | top-k 検索結果からの回答整形 |
| Crawl Agent | **Gemini 2.0 Flash** | 動的 fetch ページの要約 |
| Emergency Agent | **Gemini 2.0 Flash** (高速性重視) | RSS 新着の整理 |
| Fallback (Gemini API rate limit / quota) | Anthropic Haiku 4.5 | API key で別 vendor |

### 4.6 緊急情報プッシュの制御フロー

```
Cloud Scheduler (5 min) ─▶ Cloud Run Job (poll_rss.py)
   │
   ├─ 緊急情報 RSS fetch (fujisawa-platform.crawler.rss_poller)
   │
   ├─ 各 item の <guid> を Firestore `emergency_seen/{guid}` で重複 check
   │   - 既知 → skip
   │   - 新規 → 続行
   │
   ├─ Emergency Agent (Gemini 2.0 Flash) で要約整形
   │
   ├─ Firestore で opt-in ユーザー一覧取得 (`users/*/opt_in.emergency_push == true`)
   │
   ├─ Cloud Tasks で 500 人ずつバッチ化 (LINE Multicast 上限)
   │
   └─ LINE Multicast API で push
       - 失敗 → Cloud Tasks の retry (指数バックオフ、最大 3 回)
       - 全失敗 → DLQ + Slack 通知
```

### 4.7 リンク先 1 階層追跡の rate limit

```python
# Crawl Agent 内
MAX_LINKS_PER_QUESTION = 5
MAX_TOTAL_BYTES = 100_000  # 100 KB

async def crawl_with_links(start_url: str, query: str) -> list[FetchedPage]:
    pages = [await fetch(start_url)]
    links = extract_links(pages[0])
    # query との関連度で top-5 を選ぶ
    relevant = rank_by_relevance(links, query)[:MAX_LINKS_PER_QUESTION]
    for link in relevant:
        page = await fetch(link)
        pages.append(page)
        if total_bytes(pages) > MAX_TOTAL_BYTES:
            break
    return pages
```

### 4.8 Test Plan

- **Unit**:
  - `intent.py`: 7 カテゴリ × 50 サンプル質問で正解率 80% 以上
  - `category_routing.md` Skill の prompt が Gemini で deterministic に動く
  - `crawl_with_links` の rate limit (5 URL / 100 KB) を超えない
  - `emergency.py` の `<guid>` 重複検知
- **Integration**:
  - 実 Cloud SQL (in-memory MockEmbedding) で RAG end-to-end
  - 実 LINE webhook (ngrok 経由) → Pub/Sub → agent-core → Reply の通し
- **Manual / E2E**:
  - [ ] 30 種類の質問 (ゴミ / 防災 / 子育て / 観光 / 手続き) で出典 URL 付き回答
  - [ ] 緊急情報 RSS の dry-run (実 RSS を使うが push は send しない) で 1 週間運用
  - [ ] opt-in / opt-out のリッチメニュー UI 動作確認
  - [ ] フィードバック (👍 / 👎) が Firestore に正しく記録される

### 4.9 Migration / Rollback

- **Migration**: 新規エージェント、DB は新規作成のみ
- **Rollback**: LINE Channel 一時停止 (Webhook URL を空に) で即停止可能
- **既存ユーザー影響**: なし

### 4.10 Feature Enablement

env で段階的に機能を有効化:

| env | 既定 | 用途 |
|---|---|---|
| `FUJISAWA_INFO_BOT_RAG_ENABLED` | true | RAG Agent ON/OFF |
| `FUJISAWA_INFO_BOT_CRAWL_ENABLED` | false | リンク追跡 (Phase 2 で有効化) |
| `FUJISAWA_INFO_BOT_EMERGENCY_ENABLED` | false | 緊急情報 push (Phase 4 で有効化) |
| `FUJISAWA_INFO_BOT_LANGUAGE_DEFAULT` | ja | 既定言語 |
| `LLM_PROVIDER` | vertex | vertex / anthropic |
| `CLOUD_RUN_MIN_INSTANCES_API` | 0 | Webhook 用 Cloud Run の min instances (災害時等で 1 に切替可) |
| `CLOUD_RUN_MIN_INSTANCES_AGENT` | 0 | agent-core 用 Cloud Run の min instances |

---

## 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform (`service_name="fujisawa-info-bot"`) で計装
- 重要メトリクス:
  - `webhook.duration_ms` (3 秒以内が必須)
  - `intent.classification_accuracy` (フィードバック済みデータで)
  - `rag.no_source_url_ratio` (出典なし応答の比率)
  - `emergency.push_failure_rate`
  - `llm.cost_per_message_jpy`

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| Webhook 3 秒タイムアウト | agent-core が遅い → Pub/Sub 即返却済か確認、agent 側は Loading Indicator + Push パターン |
| RAG が出典なし回答 | Cloud SQL の pages テーブル空、または index 未作成 → 週次クロール確認、`init_schema.py` 再実行 |
| 緊急情報 push 抜け | Cloud Tasks のキュー詰まり、Multicast の rate limit → DLQ 確認、Slack alert |
| Gemini 2.5 Pro 4xx | quota / rate limit → Haiku 4.5 fallback、env で `LLM_PROVIDER=anthropic` 切替 |

### 5.3 Dependencies

- **新規**:
  - `langgraph` (Supervisor)
  - `langchain-google-vertexai`
  - `line-bot-sdk` (公式 Python SDK、v3+)
  - `google-cloud-tasks`
  - `google-cloud-pubsub`
  - `feedparser` (RSS poll)
- **path dep**: `fujisawa-platform`, `analytics-platform`
- **GCP サービス**: Cloud Run / Cloud SQL / Vertex AI / Firestore / Pub/Sub / Cloud Tasks / Cloud Scheduler

### 5.4 Non-Functional Requirements

#### 性能
- Webhook: 即 200 (Pub/Sub 投入のみ、< 200ms)
- RAG 応答: top-5 検索 + Gemini Flash 応答整形で < 3 秒
- Crawl Agent (リンク追跡): 5 URL × 3 秒 = 最大 15 秒 → Loading Indicator + Push パターン
- 緊急情報 push: RSS 更新から 5 分以内に 全 opt-in に配信

#### コスト (月間 1 万メッセージ想定)
- Gemini 2.0 Flash: 1 メッセージ ≈ ¥0.05 → 月 ¥500
- Gemini 2.5 Pro (Supervisor、20% 程度): 1 呼出 ≈ ¥0.5 → 月 ¥1,000
- Cloud Run (api / agent-core、**min=0**): 月 ¥500-1,500 (アイドル時は ¥0、リクエスト時のみ課金)
- Cloud SQL (instance 共有): ¥0 増
- Vertex Embedding: 月 ¥10
- LINE Push (Free 1,000/月、Premium ¥5/通): 緊急情報 1,000 通までは無料、超過分のみ課金
- 合計: **月 ¥2,000-3,500** (1 万メッセージ想定、緊急情報は別)

##### コールドスタート対策 (min=0 採用のため)

Webhook の LINE 3 秒タイムアウトは、Cloud Run のコールドスタート (FastAPI 起動 1-3 秒) と
ぶつかる可能性がある。以下で吸収:

- **Webhook handler を最小化**: 署名検証 + Pub/Sub publish のみ、heavy import は避ける
- **Cloud Run の Startup CPU Boost を ON**: コールドスタートを 50-70% 短縮
- **lazy load**: LangGraph / Anthropic SDK は agent-core 側のみ、webhook handler では import しない
- **Pub/Sub 投入後は async**: agent-core はコールドスタートしても LINE 側はタイムアウトしない (Push パターン)
- **ユースケース次第で min=1 に切替**: 災害時に大量 push したい場合のみ env で切替可能

#### プライバシー / データ保持
- LINE userId は Firestore のみ、ログには sha256 hash で出す
- 質問内容は session 30 日 TTL、フィードバックは永続
- 個人情報を含む質問 (住所等) は LLM に送信前にマスク (security-platform proxy 経由で DLP)

#### キャパシティ
- 同時友だち数 1,000 まで想定 (個人プロジェクト規模)
- 緊急情報 push: 1,000 人 × 1 push = 月 1,000 通 (LINE Free 枠内)
- メッセージ: 月 10,000 メッセージ想定

---

## 6. Drawbacks

- **コスト試算 ¥3,000-5,000 は当初仕様 (¥5,000 以下) 上限ギリギリ**: ユーザー増 + 複雑質問増で超過リスク。Pro モデルの利用率を制限する設計が肝
- **緊急情報誤通知のリスク**: 1 度誤 push すると信頼を失う。dry-run + 重複検知 + 1 週間 staging 必須
- **多言語対応がリンク誘導のみ**: 「自然な英語で回答」を期待するユーザーは満足しないが、藤沢市公式翻訳が既にあるので自前で書く価値が薄い
- **コールドスタート受容**: min=0 採用のため初回リクエストは 1-3 秒の遅延あり。Webhook は handler 最小化 + Startup CPU Boost で対処、agent-core は Pub/Sub 経由なので影響なし

これらを踏まえても、藤沢市民の QoL 向上 + `fujisawa-platform` 共通基盤の利用例として価値あり。

## 7. Alternatives

### 案 A: 自前 RAG ではなく ChatGPT / Gemini の "browsing" 機能を使う

- **概要**: LLM 直接 web fetch で済ませる
- **却下理由**:
  - 出典 URL が藤沢市公式に限定できない (一般 web search が混入する)
  - 鮮度メタデータの管理ができない
  - 緊急情報 RSS の poll は LLM 機能では不可能
  - 共通基盤 `fujisawa-platform` を作る価値が薄れる

### 案 B: LINE Channel を保活と統合

- **概要**: 1 つの LINE Channel で info-bot と保活の両方を提供
- **却下理由**:
  - 機能スコープが大きく違う (info-bot = 全カテゴリ広く / 保活 = 専門深く)
  - 通知頻度のルールが違う (info-bot 緊急情報 push / 保活 個別タスクリマインド)
  - 友だちの opt-in / opt-out の粒度が異なる
  - ユーザーアンケートで「保活ボットは使うが緊急情報は別アカウントで欲しい」という声に対応できない
- **採用条件**: Phase 5+ で piyolog 含めた統合 LINE Bot を proposal で出すなら再評価

### 案 C: Firestore のみで Cloud SQL を使わない (Vertex Vector Search も不採用)

- **概要**: ベクトル検索を Firestore の vector search 機能に
- **却下理由**:
  - Firestore vector search は preview 段階、本番運用に不安
  - driving-license-bot 既存の pgvector パターンを流用する方が早い

### 案 D: agent-core を 1 つの Cloud Run サービスにせず Webhook と分離しない

- **概要**: Webhook handler が直接 LangGraph 呼び、Pub/Sub を挟まない
- **却下理由**:
  - LINE 3 秒タイムアウトを超える複雑質問で 500 が返る
  - Pub/Sub の queue 機能で過負荷時のスパイク吸収を捨てる

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-09 | Draft | 初稿 (本 PR、proposal 0003 / 0005 と一括) |
| 2026-05-09 | Draft 改訂 | レビュー反映: Cloud Run min instances を **min=1 → min=0** に変更 (アイドル時コスト削減)。コールドスタート対策 (handler 最小化 / Startup CPU Boost / lazy load / Pub/Sub async) を §3.3 / §5.4 に追記、env で min=1 切替可能に |
