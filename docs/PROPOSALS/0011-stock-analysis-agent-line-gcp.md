# PROPOSAL-0011: stock-analysis-agent を LINE 経由で使えるよう GCP に配備

| | |
|---|---|
| **Status** | Draft |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-06-07 |
| **Updated** | 2026-06-07 |
| **Target** | stock-analysis-agent |
| **Related PRs** | (none yet) |
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
- EDINET 連携の本番化（`EDINET_ENABLED` は既定 false のまま。別途）
- Web UI / 公開 API の提供（LINE 経由に限定）

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
   │     ├─ Vertex AI Claude (統合レポート、既存。location=us-east5)
   │     └─ チャート PNG → ImageStore (in-memory) → /image/{id}.png URL → LINE 画像メッセージ
   ├─ SQLite (ephemeral, cache + 辞書 seed)  ※MVP。永続化は Phase 2 (shared-pg)
   └─ analytics emit → Pub/Sub (PROPOSAL-0010) → GCS
Secret Manager: LINE secret/token / (EDINET key)
```

### 3.2 段階

| Phase | 内容 |
|---|---|
| **P1 (MVP)** | terraform（Cloud Run + SA + Secret Manager + AR）+ cloudbuild + 画像配信（ImageStore + `/image/{id}.png`）+ チャートを LINE 画像メッセージで返す配線 + 配備・LINE Webhook 登録・疎通 |
| **P2** | shared Cloud SQL へ移行（reports / price_cache / ticker_dictionary を永続化、SQLite→Postgres）、analytics を pubsub backend に切替 |
| **P3** | Cloud Tasks で分析を別ワーカー化（長時間分析の信頼性 / スケール）、レート制限の強化、EDINET 本番化 |

> MVP は **P1 のみ**。動いてから P2/P3 を必要に応じて。

### 3.3 Notes / Constraints / Caveats

- **Vertex AI 上の Claude の前提**: 本エージェントは Claude（Opus 系）を Vertex AI 経由で呼ぶ。Vertex AI Marketplace で
  **当該 project に Claude が承認されている**必要がある（driving-license-bot が既定 Gemini なのはこの承認待ちのため）。
  未承認なら、LLM を Gemini にフォールバックする設定 or 承認取得が前提（要確認）。location は `us-east5`（Claude on Vertex は
  asia 未提供のため、Cloud Run=asia-northeast1 から us-east5 へクロスリージョン呼び出し）。
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
| Vertex AI で Claude 未承認 → 分析が全失敗 | High | 事前確認。未承認なら Gemini フォールバック or 承認取得を P1 の前提条件にする |
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
  Secret Manager: LINE secret/token
  Vertex AI(us-east5): Claude 統合レポート
  analytics → Pub/Sub → GCS (PROPOSAL-0010)
```

### 4.2 データモデル

- MVP はスキーマ変更なし（既存 SQLite テーブル: ticker_dictionary / price_cache / reports / alerts / edinet_documents）。
  Cloud Run では ephemeral。P2 で Postgres へ（移行スクリプト or 作り直し）。

### 4.3 API

- LINE webhook（既存 `/api/line/webhook` 等）。画像配信用に **`GET /api/line/image/{image_id}.png`** を追加。

### 4.4 主要モジュール

| 区分 | 変更 |
|---|---|
| 新規: terraform | `stock-analysis-agent/terraform/`（driving-license-bot を雛形に）: Cloud Run service / SA(sa-stock-line) + IAM（Vertex AI User / Secret accessor）/ Secret Manager(LINE secret/token) / Artifact Registry / 出力 |
| 新規: cloudbuild | `cloudbuild.yaml`（piyolog/driving の build→push 型） |
| 新規: 画像配信 | `app/services/image_store.py` + `app/routes/image.py`（piyolog から移植・適応）。`config` に `public_base_url` / `image_store_*` 追加 |
| 変更: 分析→画像 | 分析完了時にチャート PNG を ImageStore に put → 画像 URL を作り、LINE 画像メッセージで push（line_handler の分析 push 経路に追加） |
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
- Cloud Run / Secret Manager / Artifact Registry / Vertex AI（Claude）/ IAM
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
- Vertex AI Claude の承認状況に依存（未承認だと前提が崩れる）。

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

### 案 D: LLM を Gemini に変更
- 概要: Vertex AI Claude 承認が無い場合に Gemini へ。
- 評価: 承認状況次第のフォールバック。分析品質の検証が要るため既定は Claude 維持、未承認時の保険として用意。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-06-07 | Draft | 初稿。stock-analysis-agent は LINE ロジック実装済・GCP 配備資産ゼロという調査結果を踏まえ、既存 LINE Bot 配備パターン（driving-license/piyolog）を踏襲した Cloud Run 配備 + チャート画像配信を MVP(P1) として提案。永続化(P2)/分散(P3) は段階導入 |
