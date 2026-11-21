# PROPOSAL-0015: ゴルフメモ・スイング動画・レッスン計測データを LINE で貯めて分析する golf-notes-agent

| | |
|---|---|
| **Status** | Draft |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-11-21 |
| **Updated** | 2026-11-21 |
| **Target** | golf-notes-agent (新規) |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## [必須] 1. Summary

練習・レッスン・ラウンドで得た気づき（テキスト）、スイング動画、レッスンの計測結果画像、スコアを
**LINE に送るだけで Mac mini 上に保存**し、あとから分析エージェントがメモ・計測値・動画・スコアを
横断して振り返りや次の練習テーマを提案できる、自分専用のサービス `golf-notes-agent` を新設する。

稼働はすべてローカル（Mac mini 上の Docker Compose）。LINE からの受け口は PROPOSAL-0013 と同じ
Tailscale Funnel で `/api/line` だけを公開する。データの正本は「LINE から届いた原本（JSON・画像・動画）」とし、
分類・OCR・解析の結果はすべて原本から再生成できる派生データとして扱う。外部に出るのは LLM API への
呼び出しのみ。

## [必須] 2. Motivation

- 練習やレッスンの気づきが、スマホのメモ・LINE のトーク・レッスン先のアプリなどに散らばっていて、
  後から「何を直していたか」「どの時期に何が良かったか」を追えない。
- スイング動画はカメラロールに埋もれ、日付・その時の課題・計測値と結びついていない。
- レッスンで出る弾道・距離などの計測値は画像でしか受け取れず、数値として推移を見られない。
- 将来エージェントに分析させるには、今のうちから**構造化しやすい形で、欠損なく**貯めておく必要がある。

### [必須] 2.1 Goals

- [ ] LINE で送ったテキスト・スイング動画・画像が、取りこぼしゼロ・二重保存ゼロで Mac mini に保存される
- [ ] レッスンの計測結果画像を OCR し、クラブ別の弾道・距離などの数値を DB に残せる（確認してから確定）
- [ ] メモ・動画・計測値・スコアが「セッション（練習 1 回 / レッスン 1 回 / ラウンド 1 回）」単位で紐づく
- [ ] LINE で自然文の質問に、根拠（日付・メモ抜粋・数値）付きで回答できる
- [ ] 同じアングルのスイング動画を時系列で比較し、変化を数値と言葉で返せる

### [必須] 2.2 Non-Goals

- 複数ユーザー対応・共有機能（自分専用。許可リストは自分の userId 1 件）
- GCP へのデプロイ（Mac mini で完結。将来必要になれば PROPOSAL-0013 の方式で追加検討）
- ラウンド動画など長尺動画の扱い（スイング動画のみ）
- スコアアプリとの自動同期（エクスポート可否を確認中。可能なら CSV の手動取り込みを Phase 2 で検討）
- Web UI（操作はすべて LINE。分析は Claude Code / Claude Desktop から MCP 経由でも行う）

## [必須] 3. Proposal

### [推奨] 3.1 User Stories

#### 3.1.1 練習中にメモを残す
打席で「右に出る。トップで左手首が甲側に折れてる」と LINE に送ると、
「📝 練習メモを保存（ドライバー / 方向性）」と返る。同じ日の動画・メモは自動で同じ練習セッションに入る。

#### 3.1.2 レッスンの計測結果を数値で残す
レッスン後に計測結果の画像を送ると、OCR 結果（クラブ・ボール初速・打ち出し角・スピン量・キャリー等）が
Flex Message で返る。「OK」で確定、誤りがあれば「キャリー 182」のように訂正して確定する。

#### 3.1.3 スイング動画を比較する
後方からのスイング動画を送ると保存され、Phase 4 以降は「先月の同アングルと比べて、トップでの頭の位置が
3cm 右にずれている」のような比較所見が返る。

#### 3.1.4 振り返りを聞く
「最近のドライバーの課題は？」と送ると、直近のメモ・計測値の推移・動画所見をもとに、
根拠となる日付と抜粋付きで回答する。週 1 回、振り返りレポートが届く。

### [推奨] 3.2 Notes / Constraints / Caveats

- **LINE のコンテンツは保存期間が限られる**ため、画像・動画は受信直後に取得して保存する。
  動画は変換完了を確認する API を待ってから取得する。
- **LINE で送った動画は圧縮される**（解像度・フレームレートが落ちる）。テンポ比など fps に依存する
  指標の精度が下がる。高画質で残したい場合の補助経路として、Mac mini 上の **取り込みフォルダ**
  （AirDrop / iCloud Drive 同期先を監視）を Phase 4 で用意する。どちらの経路でも同じ `media` テーブルに入る。
- 確認メッセージは **reply（無料）** で返す。週次レポートだけ push を使う（月の無料通数内に収まる量）。
- SQLite に書くのは backend の 1 プロセスのみ。定期処理（バックアップ・週次レポート・再解析）は
  backend 内のスケジューラで動かす（PROPOSAL-0013 §3.3 と同じ方針）。
- 外部へ送るデータは LLM API への入力（テキスト・画像・動画のキーフレーム）のみ。
  embedding はローカルモデルで作り、外に出さない。
- レッスン計測画像のフォーマット（項目名・レイアウト）は**サンプル画像の受領後に確定**する。
  それまでは「主要項目の列 + 未知項目を入れる `extra` JSON」の可変スキーマで設計しておく（§4.2）。

### [必須] 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| LINE webhook 署名検証漏れ / 他人からの送信 | High | 署名検証失敗は 401。許可リスト外 userId は silent drop。テストでカバー |
| Mac mini のディスク故障でデータ消失 | High | 日次で SQLite `.backup` + media を外部 SSD に rsync（世代管理）。月 1 で復元リハーサル |
| 受信直後の取得失敗で LINE 側の動画が失効 | High | 原本イベントを先に保存し、取得はジョブとしてリトライ（指数バックオフ）。失敗が続いたら LINE で通知 |
| OCR の誤読で誤った数値が蓄積 | Medium | 確定前に必ず確認ステップを挟む。OCR 原文・信頼度・訂正履歴を保持し、再 OCR 可能にする |
| Funnel 公開による攻撃面の増加 | Medium | 公開は `/api/line` 配下のみ。`APP_ENV=prod` で docs / 管理 API を無効化。レート制限 |
| LLM 費用の増加（動画解析・分析） | Medium | 分類は軽量モデル、OCR・分析のみ上位モデル。動画は全フレームでなくキーフレームのみ送る。月額上限を設定 |
| Mac mini 停止中はメモが届かない | Low | LINE の Webhook 再送を有効化。外部の死活監視で停止を検知して通知 |

---

## [必須] 4. Design Details

### 4.1 アーキテクチャ概略

```
 LINE アプリ（自分）── テキスト / スイング動画 / 計測結果画像 / スコア
   │
   ▼
 LINE Messaging API
   │ HTTPS (webhook)
   ▼
┌──────────────────────── Mac mini (Docker Compose) ────────────────────────┐
│ tailscale (sidecar, Funnel: /api/line のみ公開)                           │
│   │                                                                       │
│   ▼                                                                       │
│ backend (FastAPI)                                                         │
│   ├ webhook: 署名検証 → 許可リスト → raw_events へ冪等保存 → 即 200        │
│   ├ job runner (アプリ内キュー, SQLite の jobs テーブル)                    │
│   │   ├ fetch_media     LINE から画像・動画を取得し data/media/ へ         │
│   │   ├ classify_memo   メモのタグ付け・セッション紐づけ                    │
│   │   ├ ocr_lesson      計測画像 → 構造化 → 確認 Flex                       │
│   │   ├ embed           ローカル embedding → sqlite-vec                     │
│   │   └ analyze_swing   姿勢推定 (MediaPipe) + キーフレームの LLM 所見      │
│   ├ scheduler: 03:00 backup / 週次レポート / 失敗ジョブ再試行               │
│   └ agent: 分析エージェント (Claude Agent SDK, 読み取り専用ツール)          │
│                                                                           │
│ data/                                                                     │
│   ├ golf.db            SQLite (WAL) + sqlite-vec                          │
│   ├ raw/YYYY/MM/       LINE イベント原本 JSON（追記のみ）                  │
│   ├ media/YYYY/MM/     <sha256>.mp4 / .jpg（原本）                        │
│   └ derived/           キーフレーム・姿勢推定結果など（再生成可能）          │
│                                                                           │
│ mcp-golf (stdio)  ← Claude Code / Claude Desktop から読み取り専用で分析    │
└───────────────────────────────────────────────────────────────────────────┘
        │ LLM 呼び出しのみ外部へ（llm-gateway 経由。未導入の間は llm-client）
        ▼
   Claude API
   launchd: data/ を外部 SSD へ日次コピー（ホスト側はこれだけ）
```

### 4.2 データモデル

```
raw_events      line_message_id (UNIQUE), user_id, type, payload_json, received_at
                -- 原本。変更しない。派生テーブルはすべてここから再生成できる
jobs            id, kind, ref_id, status, attempts, next_run_at, last_error

sessions        id, kind (practice|lesson|round), date, place, note
memos           id, session_id, raw_event_id, text, created_at
memo_tags       memo_id, axis (club|theme|outcome|feel), value, source (llm|user)
memo_vec        memo_id, embedding  -- sqlite-vec 仮想テーブル

media           id, session_id, raw_event_id, kind (video|image), path, sha256,
                width, height, fps, duration_ms, angle (dtl|face_on|unknown), club,
                source (line|folder)

lesson_captures id, session_id, media_id, ocr_model, ocr_raw_json, status (pending|confirmed|rejected)
launch_metrics  id, capture_id, shot_no, club, ball_speed, club_speed, smash_factor,
                launch_angle, spin_rate, spin_axis, carry, total, offline, apex,
                extra_json, confidence_json
                -- 列は一般的な項目の仮置き。サンプル画像受領後に確定し、未知項目は extra_json
metric_edits    metric_id, field, before, after, edited_at   -- 訂正履歴

rounds          id, session_id, course, total, putts, fairways_hit, gir, penalties, source
holes           round_id, hole_no, par, strokes, putts, fw, gir, penalty

swing_analyses  id, media_id, method (pose|llm), version, keyframes_json, metrics_json,
                findings_text, created_at
                -- method と version を残し、解析手法を変えても過去と比較・再計算できる
```

### 4.3 API

| エンドポイント | 公開 | 内容 |
|---|---|---|
| `POST /api/line/webhook` | Funnel で公開 | LINE webhook。署名検証・許可リスト・冪等保存 |
| `GET /healthz` | ローカルのみ | 死活監視 |
| `POST /admin/reprocess` | ローカルのみ（`APP_ENV=dev`） | 原本から派生データを再生成 |

LINE 上のコマンド（リッチメニューからも呼べる）:

| 入力 | 動作 |
|---|---|
| 自由文 | メモとして保存（Phase 2 から自動分類） |
| 動画 | スイング動画として保存。直後に「後方？正面？ クラブは？」を Quick Reply で聞く |
| 画像 | レッスン計測画像として OCR（Phase 2）。スコアカード等との判別は LLM で行い、迷ったら Quick Reply で聞く |
| `練習開始` / `レッスン開始` / `ラウンド開始 <コース名>` | セッションを明示的に開始 |
| `スコア 92 パット34 FW7/14 パーオン5` | スコアとして抽出 → 確認 |
| `取消` | 直前の 1 件を論理削除 |
| `? <質問>` | 分析エージェントに質問（Phase 3） |

### 4.4 主要モジュール

```
golf-notes-agent/
├ app/
│ ├ line/        webhook, 署名検証, reply/push, Flex テンプレート
│ ├ ingest/      raw_events 保存, media 取得, 取り込みフォルダ監視 (Phase 4)
│ ├ jobs/        SQLite キュー, ワーカー, リトライ
│ ├ enrich/      分類, セッション紐づけ, スコア抽出, レッスン OCR
│ ├ swing/       キーフレーム抽出 (ffmpeg), 姿勢推定 (MediaPipe), 指標計算, 比較
│ ├ search/      ローカル embedding, sqlite-vec
│ ├ agent/       分析エージェントとツール定義 (sql_readonly, search_memos, get_metrics, compare_swings)
│ ├ storage/     DB リポジトリ, メディアの保存先
│ └ scheduler/   backup, 週次レポート
├ mcp/           golf-data MCP サーバ (読み取り専用)
├ migrations/    alembic
├ config/        local.env.example, tailscale-serve.json
├ docker-compose.yml
└ tests/
```

スイング解析の指標（Phase 4、後方・正面で別定義）:
頭の移動量、前傾角の変化、肩・腰の回転差（近似）、テンポ比（バックスイング : ダウンスイング）、
アドレス / トップ / インパクト / フィニッシュのキーフレーム。

### [必須] 4.5 Test Plan

- **Unit**: 署名検証、許可リスト、冪等キー、スコア文字列の抽出、OCR 結果 → `launch_metrics` の正規化、
  スイング指標の計算（固定のキーポイント列を入力）
- **Integration**: webhook → raw_events → jobs → media 保存までを LINE API をモックして通す。
  リトライと失効時の通知。SQLite のバックアップ・復元
- **Golden**: レッスン計測画像のサンプル（受領後）を固定入力にし、OCR 結果の期待値と項目一致率を計測。
  モデル・プロンプト変更時の回帰検知に使う
- **Manual**: 実機の LINE で各メッセージ種別を送信、Funnel 経由で届くことを確認。月 1 で復元リハーサル
- カバレッジ 80% 以上（LLM 呼び出し部はモック）

### [推奨] 4.6 Migration / Rollback

新規モジュールのため移行なし。派生データは `POST /admin/reprocess` で原本から再生成できるので、
分類・OCR・解析ロジックの変更は「新バージョンで再生成 → 比較 → 切替」でロールバック可能。

### [推奨] 4.7 Feature Enablement

フェーズごとに env フラグで有効化する（`ENABLE_CLASSIFY` / `ENABLE_LESSON_OCR` / `ENABLE_AGENT` /
`ENABLE_SWING_ANALYSIS`）。Phase 1 の保存機能はフラグなしで常に有効。

---

## [推奨] 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform（ローカル JSONL）に `memo_ingested` / `media_saved` / `job_failed` /
  `lesson_ocr_confirmed` / `llm_call`（費用・トークン）を emit
- Healthchecks.io への ping で死活監視（PROPOSAL-0013 と同じ）

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| LINE の「検証」が失敗する | Funnel 無効 / sidecar 停止 / パス違い。`tailscale funnel status` を確認 |
| 動画が保存されない | 変換待ちのタイムアウト。`jobs` の `last_error` を確認し、`fetch_media` を再実行 |
| OCR の項目がずれる | 計測画像のレイアウト変更。golden テストで差分を確認し、プロンプトを更新して再 OCR |

### 5.3 Dependencies

Tailscale (Funnel)、line-bot-sdk v3、Claude API（llm-gateway / llm-client）、ffmpeg、MediaPipe、
sqlite-vec、ローカル embedding モデル（多言語対応のもの）、analytics-platform (path dep)

### [推奨] 5.4 Non-Functional Requirements

#### 性能 (Performance)
webhook は 1 秒以内に 200 を返す。保存確認の返信は 10 秒以内、OCR の確認 Flex は 30 秒以内。

#### コスト (Cost)
インフラ費は 0（既存の Mac mini と Tailscale 無料枠）。LLM 費は月額上限を設定し、超過時は分析系を停止して保存のみ継続。

#### プライバシー / データ保持
データは Mac mini と外部 SSD のみに保存。LLM API には必要最小限（動画はキーフレームのみ）を送る。原本は無期限保持。

#### キャパシティ
スイング動画 1 本 5〜20MB × 月 50 本 ≒ 月 1GB 未満。数年分でも数十 GB 程度。

## [推奨] 6. Drawbacks

- Mac mini が単一障害点になる（停止中は受信できず、ディスク故障リスクもバックアップ頼み）
- LINE 経由の動画は圧縮されるため、解析精度に上限がある（取り込みフォルダで補完）

## [必須] 7. Alternatives

### 案 A: GCP (Cloud Run + GCS + shared-pg) で稼働
常時受信でき、Mac mini 停止の影響を受けない。ただし「全部ローカルで動かしたい」という要件に反し、
動画の解析（MediaPipe）を Cloud Run で動かすとコストと構成が膨らむため不採用。
受信だけ GCP に置く構成も、書き込み先が 2 か所になり整合性管理が増えるため不採用。

### 案 B: LINE を使わず、iCloud 共有フォルダ / メモアプリから取り込む
動画の画質は最良だが、テキストメモの手軽さと確認・訂正の対話（Flex / Quick Reply）が失われる。
主経路は LINE とし、高画質動画の補助経路として取り込みフォルダを採用（Phase 4）。

### 案 C: Postgres + pgvector をローカルで動かす
機能的には十分だが、自分専用・単一プロセスの規模では SQLite + sqlite-vec の方が運用・バックアップが単純。
将来 GCP に移す場合は PROPOSAL-0013 の db_copy 方式で移行できる。

## [必須] 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-11-21 | Draft | 初稿 |

### 実装フェーズ

| Phase | 内容 | 完了条件 |
|---|---|---|
| 1 MVP | webhook・許可リスト・冪等保存・media 取得・取消・バックアップ・Funnel | 1 か月使って取りこぼしゼロ |
| 2 | メモ分類・セッション化・**レッスン計測 OCR**・スコア抽出・リッチメニュー | 計測値とスコアが確定データとしてたまる |
| 3 | ローカル embedding・LINE での QA・週次レポート・MCP サーバ | 根拠付きで質問に答えられる |
| 4 | スイング解析（姿勢推定・キーフレーム所見・時系列比較）・取り込みフォルダ | 同アングル動画の変化を数値と言葉で返せる |
| 5 | スコアアプリ CSV 取り込み（可能なら）・次の練習テーマの自律提案 | — |
