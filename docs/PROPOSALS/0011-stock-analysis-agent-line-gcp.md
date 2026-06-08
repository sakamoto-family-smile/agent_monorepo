# PROPOSAL-0011: stock-analysis-agent を LINE 経由で使えるよう GCP に配備

| | |
|---|---|
| **Status** | Implementing |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-06-07 |
| **Updated** | 2026-06-07 |
| **Target** | stock-analysis-agent |
| **Related PRs** | P1 実装 (本ブランチ) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

`stock-analysis-agent` は **LINE Bot ロジック（`分析 <銘柄>` コマンド・署名検証・ack→push の非同期パターン）を
既に実装済み**だが、**GCP 配備の一式（terraform / cloudbuild / Secret Manager / 画像配信 / DB 永続化判断）が
無く**、ローカルでしか動かせない。本提案は、既存の LINE ロジックをそのまま活かして **Cloud Run に配備し、
LINE から `分析 トヨタ` のように呼べる本番サービス**にすることを目的とする。

配備パターンは monorepo の既存 LINE Bot（`driving-license-bot` / `piyolog-analytics` / `fujisawa-info-bot`）を
踏襲し、新規発明を避ける。LLM は Vertex AI 上の Claude（既存設定）を使う。チャート画像は LINE に画像メッセージで
返せるよう配信経路を追加する。MVP を最優先し、永続化・分散非同期は段階導入する。

## 2. Motivation

- 株価分析エージェントは実装が揃っているのに**手元でしか使えず**、LINE から手軽に使えない。
- 既存 LINE Bot（piyolog / driving-license / fujisawa-info-bot）の Cloud Run 配備パターンが確立しており、
  **同じ型に乗せれば低リスクで配備できる**。
- 個人運営のため、まず**動くものを最短で**（MVP）出し、永続化や分散化は必要になってから足す。

### 2.1 Goals

- [ ] **LINE から `分析 <銘柄>` で本番分析が返る**（テキストレポート + チャート画像）
- [ ] **Cloud Run に配備**（terraform + cloudbuild + Secret Manager + Artifact Registry、既存パターン踏襲）
- [ ] **チャート画像を LINE に返す**（画像配信経路を追加。piyolog の ImageStore 方式を流用）
- [ ] LINE webhook の**非同期処理（ack→push）が Cloud Run 上で確実に動く**構成にする
- [ ] **アクセス制御 / コスト上限**（allow-list、分析回数のレート制限）を持つ
- [ ] analytics-platform に **pubsub backend** で接続（PROPOSAL-0010 の成果を流用）

### 2.2 Non-Goals

- 分析ロジック自体の改修（既存の ticker 解決 / yfinance / 指標 / Claude 統合をそのまま使う）
- **SQLite → Cloud SQL の本格移行**（MVP は ephemeral SQLite で割り切る。永続化は Phase 2）
- Cloud Tasks による分散非同期（MVP は同一インスタンス内 BackgroundTasks。Phase 2 で検討）
- **複数銘柄を1コマンドで同時分析**（現状 `分析 <1銘柄>`。複数は複数コマンドで。バッチは将来）
- LLM を Vertex AI 経由に変更（MVP は既存の Anthropic OAuth token 経路。Vertex は将来オプション、§7 案D）
- Web UI / 公開 API の提供（LINE 経由に限定）

> **EDINET 連携について（レビュー指摘）**: EDINET は本 agent に**実装済み**（`edinet_collector.collect_filings` /
> `edinet-client[xbrl]` path dep / proposal 0006）だが **`EDINET_ENABLED` 既定 false** で無効。本提案では
> **P3 で有効化**（`EDINET_API_KEY` を Secret Manager + `EDINET_ENABLED=true`）を扱う。有効化すると Claude が
> XBRL/PDF を読むため分析が長くなる（1〜5分）。MVP(P1) では無効のまま。別 proposal に切り出しても良い。

---

## 3. Proposal

既存 LINE ロジックを**配備可能にする**ことに集中する。新規実装は「GCP 配線」と「画像配信」のみ。

### 3.1 構成（MVP）

```
LINE Platform
   ↓ webhook (署名検証, 即時 200)
Cloud Run: stock-analysis-line (FastAPI, min_instances=1)
   ├─ 分析コマンド: Reply で ack → BackgroundTasks で分析 → 完了後 Push
   │     ├─ ticker 解決 / yfinance / 指標 / mplfinance チャート (既存)
   │     ├─ Claude(claude-opus-4-6) 統合レポート ※Anthropic OAuth token 経由 (既存・Vertex 不要)
   │     ├─ brave-search MCP (npx, in-process) でニュース/センチメント
   │     ├─ チャート PNG → ImageStore → /image/{id}.png URL → LINE 画像メッセージ
   │     └─ 全文 Markdown → ReportStore → /report/{id}.md (attachment) URL → LINE で「全文DL」リンク
   ├─ SQLite (ephemeral, cache + 辞書 seed)  ※MVP。永続化は Phase 2 (shared-pg)
   └─ analytics emit → Pub/Sub (PROPOSAL-0010) → GCS
Secret Manager: LINE secret/token / CLAUDE_CODE_OAUTH_TOKEN / BRAVE_API_KEY
```

### 3.2 段階

| Phase | 内容 |
|---|---|
| **P1 (MVP)** | terraform（Cloud Run + SA + Secret Manager + AR）+ cloudbuild + 画像配信（ImageStore + `/image/{id}.png`）+ チャートを LINE 画像メッセージで返す配線 + 配備・LINE Webhook 登録・疎通 |
| **P2** | shared Cloud SQL へ移行（reports / price_cache / ticker_dictionary を永続化、SQLite→Postgres）、analytics を pubsub backend に切替 |
| **P3** | Cloud Tasks で分析を別ワーカー化（長時間分析の信頼性 / スケール）、レート制限の強化、**EDINET 有効化**（`EDINET_API_KEY` + `EDINET_ENABLED=true`） |
| **将来** | LLM 経路を **Vertex AI Claude** に切替（要 Vertex で Claude 承認、§7 案D）、複数銘柄バッチ分析 |

> MVP は **P1 のみ**。動いてから P2/P3 を必要に応じて。

### 3.3 Notes / Constraints / Caveats

- **Claude の認証は Anthropic OAuth トークン（Vertex 不要）**: 本エージェントは `claude-agent-sdk` で
  `model="claude-opus-4-6"` を **`CLAUDE_CODE_OAUTH_TOKEN`（Anthropic サブスクの OAuth トークン）経由**で呼ぶ
  （`orchestrator.py`、`ANTHROPIC_API_KEY=""` / Vertex env なし）。**Vertex AI 上の Claude 承認は不要**。
  GitHub Action（PR #186）で使った `CLAUDE_CODE_OAUTH_TOKEN` と同種（`claude setup-token` で取得、有効期限1年）。
  コストは Anthropic の **Agent SDK 月次クレジット枠**から（2026-06-15 以降の枠。GitHub Action と同じ）。
  ※ config の `VERTEX_AI_LOCATION` は現状 LLM 経路では未使用の名残。
- **brave-search MCP は in-process（npx）**: `@modelcontextprotocol/server-brave-search` を npx 起動するため、
  コンテナに **Node.js が必要**（既存 Dockerfile に同梱済）+ **`BRAVE_API_KEY`** が要る。
- **Cloud Run の BackgroundTasks**: レスポンス返却後の処理はインスタンスが凍結/破棄されると途中で止まる。**`min_instances=1`
  かつ CPU always-allocated** にして ack→push を確実にする（常時起動コストとのトレードオフ）。将来は Cloud Tasks（P3）。
- **ephemeral SQLite**: Cloud Run 再起動で cache / reports が消える。`ticker_dictionary` はイメージに seed し、price_cache は
  再取得で復元（yfinance 呼び出しが増えるが個人利用なら許容）。永続化が要れば P2。
- **画像配信**: in-memory ImageStore は再起動で消えるが、画像 URL は分析直後の短時間のみ使うため実用上問題ない
  （TTL + ランダム ID）。LINE が URL を取得する間だけ持てばよい。
- **コスト**: `min_instances=1` の常時起動（小） + Claude 分析の従量（**1 分析が高め**）。allow-list + レート制限で濫用防止。

### 3.4 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| CLAUDE_CODE_OAUTH_TOKEN 未設定/失効 → 分析が全失敗 | High | Secret Manager に有効なトークンを登録（`claude setup-token`、有効期限1年）。失効監視 |
| BRAVE_API_KEY 未設定 → センチメント取得失敗 | Medium | Secret Manager に登録。未設定でも分析本体は継続（ニュースのみ欠落）するよう確認 |
| BackgroundTasks がインスタンス破棄で途中終了 | Medium | min_instances=1 + CPU always-allocated。失敗時は push でエラー通知（既存）。恒久的には Cloud Tasks(P3) |
| Claude Opus 分析のコスト増大 | Medium | allow-list（家族のみ）+ レート制限（1 ユーザー日次上限）。分析は明示コマンド時のみ |
| ephemeral SQLite で履歴消失 | Low | MVP は許容（cache は再生成）。永続化は P2 (shared-pg) |
| チャート画像 URL の漏洩 | Low | ランダム ID + 短 TTL。公開バケットを使わず Cloud Run 自身が配信 |
| LINE webhook の遅延 (>3s) で再送 | Medium | 即時 200 を返す既存実装（分析は background）。署名検証のみ同期 |

---

## 4. Design Details

### 4.1 アーキテクチャ（Before / After）

```
Before: ローカルのみ。FastAPI + LINE webhook 実装済だが GCP 配備資産ゼロ。チャートは生成のみ(LINE 未送信)。

After (P1/MVP):
  LINE → Cloud Run(stock-analysis-line) webhook
    → 分析(既存) → テキスト push + チャート画像 push (ImageStore 経由 URL)
  Secret Manager: LINE secret/token / CLAUDE_CODE_OAUTH_TOKEN / BRAVE_API_KEY
  Claude (claude-opus-4-6, Anthropic OAuth token 経由・Vertex 不要): 統合レポート
  analytics → Pub/Sub → GCS (PROPOSAL-0010)
```

### 4.2 データモデル（DB に保存される内容・履歴）

既存 SQLite（`services/database.py`）のテーブル:

| テーブル | 内容 | 履歴か |
|---|---|---|
| `ticker_dictionary` | 企業名↔ティッカーの辞書（alias/market） | 種データ |
| `price_cache` | yfinance OHLCV のキャッシュ（TTL） | キャッシュ |
| **`reports`** | **分析結果（ticker / company / report_data JSON / created_at）** | **= 分析履歴** |
| `alerts` | 価格アラート（最小限） | 設定 |
| `edinet_documents` | EDINET 提出書類インデックス | 索引 |

- **分析履歴は `reports` テーブルに保存される**。ただし **MVP(P1) は Cloud Run の ephemeral SQLite なので、
  再起動で履歴/キャッシュは消える**（cache は再取得で復元）。**永続的な履歴が要れば P2 で shared Cloud SQL へ**
  （SQLite→Postgres 移行 or 作り直し）。
- MVP はスキーマ変更なし。

### 4.3 API / LINE での結果の渡し方

`分析 <銘柄>` は ack を Reply で返したあと、分析完了後に **LINE Push** で結果を送る。配信は **3 点セット**:

| 種別 | 中身 | 配信方法 |
|---|---|---|
| **要約** | 主要指標 + 結論サマリ | **LINE Flex バブル**（`analysis_summary_bubble`、不可時テキスト fallback） |
| **チャート** | mplfinance のローソク足 PNG | **LINE 画像メッセージ**（`GET /api/line/image/{id}.png` の URL を push） |
| **全文レポート** | Claude が生成した**全文（Markdown）** | **ファイルとしてホストし URL を LINE で渡す**（下記） |

- **全文 Markdown を添付ファイルとして取得（レビュー指摘）**:
  LINE Bot には任意ファイルの「添付」メッセージ型が無いため、**全文 Markdown を Cloud Run 上でホストし、その URL を
  LINE（Flex のボタン「📄 全文(.md)を取得」or テキストリンク）で渡す**。エンドポイント
  **`GET /api/line/report/{report_id}.md`**（`Content-Type: text/markdown`, `Content-Disposition: attachment; filename=...md`）
  でブラウザ表示/ダウンロード可能にする。実装は画像と同じ **in-memory store（ランダム ID + TTL）**（MVP）。永続配布が要れば
  GCS（P2）。全文は既存の `reports` テーブルにも保存される。
- LINE webhook（既存 `/api/line/webhook` 等）。新規エンドポイント: 画像 `GET /api/line/image/{id}.png` /
  全文 `GET /api/line/report/{id}.md`。
- **1コマンド=1銘柄**: `target = " ".join(args)` を1クエリとして ticker 解決するため、`分析 トヨタ` のように
  1銘柄ずつ。複数企業は複数コマンドを送る（同時バッチは将来）。

### 4.4 主要モジュール

| 区分 | 変更 |
|---|---|
| 新規: terraform | `stock-analysis-agent/terraform/`（driving-license-bot を雛形に）: Cloud Run service / SA(sa-stock-line) + IAM（Secret accessor のみ。Vertex 不要）/ Secret Manager(LINE secret/token + CLAUDE_CODE_OAUTH_TOKEN + BRAVE_API_KEY) / Artifact Registry / 出力 |
| 新規: cloudbuild | `cloudbuild.yaml`（piyolog/driving の build→push 型） |
| 新規: 画像/全文配信 | `app/services/image_store.py` + `app/routes/image.py`（piyolog から移植）+ **全文 Markdown 用の store + `GET /api/line/report/{id}.md`（attachment）**。`config` に `public_base_url` / store の TTL/上限 |
| 変更: 分析→3点配信 | 分析完了時に (1) Flex 要約 (2) チャート画像 URL (3) 全文 Markdown の DL URL を組み立てて LINE Push（line_handler の分析 push 経路に追加） |
| 変更: Cloud Run 設定 | `min_instances=1` / CPU always-allocated / startup probe `/health` |
| 変更: analytics | instrumentation を `build_sink` 利用に（pubsub backend 対応、P5-3 と同型）※P2 でも可 |
| 変更: Dockerfile | 不要な Node.js を削る等の整理（任意） |

### 4.5 Test Plan

- **Unit**: 画像 ImageStore の put/get/TTL、画像 URL 生成、分析 push 経路で画像メッセージが組まれること（fake line_client）。
- **Integration**: webhook 署名検証 → 分析コマンドで ack→push（既存テストの延長）。
- **Manual / E2E（配備後）**:
  - [ ] LINE で `分析 トヨタ` → ack → 数十秒後にテキストレポート + チャート画像が届く
  - [ ] `分析 AAPL` / `分析 7203.T` でも動作
  - [ ] allow-list 外ユーザは無視 / レート制限が効く
  - [ ] Vertex AI Claude が呼べる（未承認ならフォールバック挙動）
  - [ ] analytics イベントが（pubsub 有効時）GCS に届く

### 4.6 Migration / Rollback

- 新規サービスのため移行なし。Rollback は Cloud Run リビジョン切り戻し / サービス削除。
- LINE チャネルは専用チャネルを用意（既存 Bot と混線させない）。

### 4.7 Feature Enablement

- `LINE_CHANNEL_SECRET` / `_ACCESS_TOKEN` 未設定なら webhook は 503（既存）。
- analytics backend は env（`ANALYTICS_STORAGE_BACKEND`）で local/pubsub 切替（既定 local）。
- EDINET は `EDINET_ENABLED=false`（既定）で無効のまま。

---

## 5. Operational Concerns

### 5.1 Monitoring
- Cloud Run のエラー率 / レイテンシ / インスタンス数。分析失敗（push エラー）ログ。
- 分析コスト（Vertex AI 呼び出し回数）は analytics イベントで追跡。

### 5.2 Troubleshooting
| 症状 | 対処 |
|---|---|
| 分析が返らない | BackgroundTasks がインスタンス破棄で停止 → min_instances/CPU 設定確認、Cloud Tasks 検討 |
| 画像が出ない | public_base_url / ImageStore TTL / 画像 URL を確認 |
| LLM 失敗 | Vertex AI Claude 承認 / location / SA の Vertex AI User ロール確認 |
| webhook 401 | LINE_CHANNEL_SECRET 不一致 |

### 5.3 Dependencies
- Cloud Run / Secret Manager / Artifact Registry / IAM（**Vertex は使わない**）
- Anthropic（`CLAUDE_CODE_OAUTH_TOKEN` 経由の claude-agent-sdk）/ Brave Search API（brave-search MCP）/ Node.js（npx, コンテナ同梱）
- 既存: line-bot-sdk / yfinance / mplfinance / claude-agent-sdk / analytics-platform
- LINE 専用チャネル（Messaging API）

### 5.4 Non-Functional Requirements

#### 性能
- webhook は即時 200。分析は background（30秒〜2分）。チャート生成はメモリ内。

#### コスト
- min_instances=1 の常時起動（小額）+ Claude 分析の従量（高め）。allow-list + レート制限で抑制。

#### プライバシー / 保持
- LINE userId / 分析クエリを扱う。allow-list 外は無視。reports は MVP では ephemeral。

#### キャパシティ
- 個人/家族利用の低頻度。min_instances=1 で十分。高頻度化したら Cloud Tasks + max_instances 調整。

---

## 6. Drawbacks

- `min_instances=1` の常時起動コスト（小）。回避には Cloud Tasks 化（複雑性増）。
- ephemeral SQLite のため履歴が消える（MVP 割り切り）。
- Claude 利用は Anthropic の Agent SDK 月次クレジット枠に依存（トークン失効・枠超過時に分析が止まる）。

## 7. Alternatives

### 案 A: MVP=Cloud Run + ephemeral SQLite + min_instances=1（採用）
- 概要: 既存 LINE ロジックをそのまま Cloud Run に乗せ、最短で本番化。
- 採用理由: 既存資産最大活用・低リスク・最短。永続化/分散は段階導入。

### 案 B: 最初から shared Cloud SQL + Cloud Tasks
- 概要: 永続化・分散非同期を初手から作り込む。
- 却下理由: SQLite→Postgres 移行 + Cloud Tasks 配線は MVP には重い。必要になってから（P2/P3）。

### 案 C: GCS 公開バケットでチャート配信
- 概要: チャートを GCS に置き公開 URL を LINE に渡す。
- 評価: 永続配信には良いが、MVP は Cloud Run 自身が in-memory 配信する方が簡単（バケット/IAM 不要）。P2 で検討。

### 案 D: LLM を Vertex AI Claude 経由に変更（**将来対応予定**）
- 概要: claude-agent-sdk を Vertex AI 経由（env: `CLAUDE_CODE_USE_VERTEX=1` / `ANTHROPIC_VERTEX_PROJECT_ID` /
  `CLOUD_ML_REGION`）に切替える。**ユーザー要望により後追いで対応予定**。
- 本提案での扱い: **MVP(P1) は既存の Anthropic OAuth token 経路を採用**（Vertex 承認不要・最短）。
  Vertex 切替は別フェーズ（前提: 当該 project の Vertex AI で Claude が承認されていること。location は us-east5 等）。
  切替は orchestrator の env 設定差分が中心で、コードの大改修は不要。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-06-07 | Draft | 初稿。stock-analysis-agent は LINE ロジック実装済・GCP 配備資産ゼロという調査結果を踏まえ、既存 LINE Bot 配備パターン（driving-license/piyolog）を踏襲した Cloud Run 配備 + チャート画像配信を MVP(P1) として提案。永続化(P2)/分散(P3) は段階導入 |
| 2026-06-07 | Draft (訂正) | LLM 認証経路を確認: **Vertex AI ではなく Anthropic OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) 経由**（orchestrator.py）と判明。「Vertex Claude 承認」前提を撤回し、必要 Secret を LINE secret/token + `CLAUDE_CODE_OAUTH_TOKEN` + `BRAVE_API_KEY` に修正。brave-search は npx in-process（Node.js 同梱） |
| 2026-06-07 | Draft (レビュー反映) | PR #199 のレビュー反映: ① Vertex は将来オプションと明記（§7 案D）② テキストレポートの配信方法（Flex バブル + テキスト fallback 先頭~1500字、Push）を §4.3 に追記 ③ EDINET は実装済(既定 false)→ P3 で有効化と明記 ④ DB 保存内容/履歴（reports=分析履歴、MVP は ephemeral）を §4.2 に詳述 ⑤ 1コマンド=1銘柄（複数はバッチ将来）を明記 |
| 2026-06-07 | Draft (レビュー反映2) | 配信方法を更新: **要約=Flex / チャート=画像 / 全文=Markdown を `GET /api/line/report/{id}.md`（attachment）でホストし URL を LINE で渡す** 3点セットに（ユーザー要望「全文を DL ファイルで」）。ReportStore + エンドポイントを §4.3/§4.4 に追加 |
| 2026-06-08 | Implementing (P3-A) | **P3-A: Cloud Tasks 分散非同期 + GCS media**。分析を webhook の in-process BackgroundTasks から **Cloud Tasks queue + 別 worker Cloud Run** に委譲（流量制御 / 自動リトライ / 永続化 → webhook・worker とも min=0 可）。app: `task_queue.enqueue_analysis`、`routes/tasks.py`（worker `/api/tasks/analyze`、OIDC token を app 内検証、`X-CloudTasks-TaskRetryCount` でリトライ判定）、`media.py`（memory\|gcs。worker 複数 instance 対応のため **チャート/全文を GCS にアップロードして公開 URL を返す**）、`line_handler` は tasks_enabled 時に enqueue（失敗時 in-process フォールバック）。config に TASKS_*/MEDIA_* 追加、pyproject に google-cloud-tasks。terraform: Cloud Tasks queue + worker service（同一イメージ・public・min=0）+ media GCS バケット（public read / 1 日 TTL）+ invoker SA + IAM（enqueuer / serviceAccountUser / cloudtasks token creator / objectAdmin）。test 追加（220 passed）。残: **P3-B EDINET 有効化**（edinet_documents の Cloud SQL 移行 + index batch Job/Scheduler + Edinetcode.csv + cache GCS + EDINET_ENABLED=true、別 PR） |
| 2026-06-07 | Implementing (P2-B) | **P2-B: SQLite → shared Cloud SQL (Postgres) 移行**。core 4 テーブル (ticker_dictionary / price_cache / reports / alerts) を **SQLAlchemy async** 化 (`db_models.py` / `db_engine.py`、`database.py` の 6 関数はシグネチャ・戻り値互換のまま内部置換)。**alembic** 導入 (env.py は `config.resolved_database_url` 再利用、0001_initial)。config に `database_url` / DB 分割指定 / `resolved_database_url` / `db_auto_create` 追加 (DATABASE_URL > DB_HOST/USER/NAME 組立 > sqlite)。Dockerfile は `RUN_MIGRATIONS=true` 時に起動時 `alembic upgrade head`。terraform で shared-pg に `stock_analysis_db` + `stock_analysis_user` (ABANDON) + DB password secret 作成、Cloud Run に Cloud SQL connector + DB env + `DB_AUTO_CREATE=false`。**EDINET (edinet_documents + edinet_index_repo) は EDINET 有効化 (P3) まで aiosqlite 据え置き** (batch は repo の `ensure_schema()` で自己完結)。test 追加 (203 passed)。手動ステップ: apply 後に `stock_analysis_user` へ schema 権限 GRANT (terraform/README.md)。これで P2 完了、残: P3 (Cloud Tasks + EDINET 有効化) |
| 2026-06-07 | Implementing (P2-A) | P2 を 2 PR に分割し analytics 先行。**P2-A: analytics → Pub/Sub 入口切替**。`instrumentation/setup.py` を `build_sink` + `PubSubAnalyticsConfig`（backend=pubsub のとき `PubSubSink`、それ以外は従来の RotatingFileSink/uploader を温存）に。config に `analytics_pubsub_topic` / `analytics_gcp_project` 追加、pyproject を `analytics-platform[gcs,pubsub]` に（uv.lock 更新）、terraform で Cloud Run env を `ANALYTICS_STORAGE_BACKEND=pubsub` + topic/project に切替。publish 権限は analytics-platform 側 `publisher_service_account_emails` に stock SA を追記して付与（cross-module 手動ステップ、terraform/README.md 参照）。test 追加（190 passed）。残: **P2-B Cloud SQL 移行**（SQLAlchemy async + alembic、別 PR） |
| 2026-06-07 | Implementing (P1) | PR #199 マージ後、P1 実装に着手。実装内容: ① `BlobStore`（チャート PNG / 全文 Markdown の LRU+TTL store）+ `routes/media.py`（`GET /api/line/image/{id}.png` / `GET /api/line/report/{id}.md`）② `line_client.push_image` ③ `analysis_summary_bubble` に全文 DL ボタン ④ `line_handler` を 3 点配信（Flex 要約 / チャート画像 / 全文 .md）に + allow-list + 日次レート制限（`access_control.py`）⑤ Dockerfile を repo ルート context のマルチステージ build に刷新（analytics-platform / edinet-client path dep 同梱 + Node.js + `@anthropic-ai/claude-code` CLI + 日本語フォント、port 8080）⑥ `cloudbuild.yaml` + gcloudignore ⑦ terraform 一式（Cloud Run min=1/CPU always-allocated・SA・Secret 4 件・Artifact Registry、Cloud SQL/Vertex 不使用）。unit test 追加（188 passed）。LINE チャネル作成・Secret 値投入・Webhook 登録・PUBLIC_BASE_URL 反映は deploy 時の手動ステップ（terraform/README.md 参照） |
