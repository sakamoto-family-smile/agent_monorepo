# PROPOSAL-0016: ゴルフメモ・スイング動画・レッスン計測データを LINE で貯めて分析する golf-notes-agent

| | |
|---|---|
| **Status** | In Review |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-11-21 |
| **Updated** | 2026-11-22 |
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
- [ ] レッスンの計測結果テキストを LINE に貼るだけで、クラブ別の弾道・距離などの数値が DB に残る（画像しかない場合は OCR で補完）
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
練習場に着いたらリッチメニューの「▶ 開始/終了」→「練習」を押す。打席で「右に出る。トップで左手首が甲側に折れてる」と
送ると、「📝 練習メモを保存（ドライバー / 方向性）」と返る。終了を押すまでに送ったメモ・動画・計測は同じ練習セッションに入る。

#### 3.1.2 レッスンの計測結果を数値で残す
リッチメニューの「📊 計測」を押してから、計測結果のテキスト（日時・クラブ・飛距離・キャリー…の 15 項目）を貼ると、
ルールベースで解析して即保存し、「⛳ 7I 1 球を保存（キャリー 131.4yd / 左 6.5yd）」と返る。
計測モードは 30 分続くので、何回かに分けて貼ってもよい。検算に引っかかった球だけ Flex Message で確認を求める。
ボタンを押し忘れて貼っても自動判定で保存され、「計測として保存しました（違えば取消）」と返る。
テキストが無く画像しかない場合は OCR して、確認後に確定する。

#### 3.1.3 スイング動画を比較する
「🎥 動画」→「後方」→「7I」と選んでからスイング動画を送ると、アングルとクラブ付きで保存され、Phase 4 以降は「先月の同アングルと比べて、トップでの頭の位置が
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
- **送る種類はリッチメニューで先に選ぶ**のを主経路とし、自動判定は押し忘れたときの予備とする（§4.3.1）。
  意図がはっきりするので、書式が崩れていても「計測として読めない行」を具体的に返せる。
  動画のアングル・クラブやセッションの区切りも、推測ではなく明示的に記録できる。
- 確認メッセージは **reply（無料）** で返す。週次レポートだけ push を使う（月の無料通数内に収まる量）。
- SQLite に書くのは backend の 1 プロセスのみ。定期処理（バックアップ・週次レポート・再解析）は
  backend 内のスケジューラで動かす（PROPOSAL-0013 §3.3 と同じ方針）。
- 外部へ送るデータは LLM API への入力（テキスト・画像・動画のキーフレーム）のみ。
  embedding はローカルモデルで作り、外に出さない。
- レッスン計測画像の項目は 2026-11-21 受領のサンプル（1 球ごとの 15 項目）で確定した（§4.2.1）。
  レイアウト変更や未知の項目に備え、確定列に入らない項目は `extra_json` に原文のまま残す。

### [必須] 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| LINE webhook 署名検証漏れ / 他人からの送信 | High | 署名検証失敗は 401。許可リスト外 userId は silent drop。テストでカバー |
| Mac mini のディスク故障でデータ消失 | High | 日次で SQLite `.backup` + media を外部 SSD に rsync（世代管理）。月 1 で復元リハーサル |
| 受信直後の取得失敗で LINE 側の動画が失効 | High | 原本イベントを先に保存し、取得はジョブとしてリトライ（指数バックオフ）。失敗が続いたら LINE で通知 |
| 計測テキストの書式変更で解析が漏れる / OCR の誤読 | Medium | 未知の行は `extra_json` に残し、必須項目が欠けたら確認を求める。原文・訂正履歴を保持し、パーサ更新後に原本から再解析。OCR は確定前に必ず確認 |
| 入力モードの解除忘れで、メモが計測・スコア扱いになる | Medium | モードは 30 分で自動解除。モード中に解析できないテキストは捨てずに「メモとして保存しますか？」と聞く。返信には毎回いまのモードを表示 |
| セッションの終了忘れで、翌日のデータが前日のセッションに入る | Low | 最終操作から 6 時間、または日付が変わったら自動で終了。あとから `session_id` を付け替えられるようにする |
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
│   │   ├ parse_lesson    計測テキスト → 構造化 (ルールベース, LLM 不要)      │
│   │   ├ ocr_lesson      計測画像しか無い場合 → OCR → 確認 Flex             │
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

sessions        id, kind (practice|lesson|round), date, place, note,
                started_at, ended_at, end_reason (manual|idle|date_change)
input_modes     user_id (PK), mode (memo|metrics|video|score|ask), params_json,
                session_id, expires_at
                -- いまの入力モード。動画モードの params_json に angle / club を持つ
memos           id, session_id, raw_event_id, text, created_at
memo_tags       memo_id, axis (club|theme|outcome|feel), value, source (llm|user)
memo_vec        memo_id, embedding  -- sqlite-vec 仮想テーブル

media           id, session_id, raw_event_id, kind (video|image), path, sha256,
                width, height, fps, duration_ms, angle (dtl|face_on|unknown), club,
                source (line|folder)

lesson_captures id, session_id, source (text|image), raw_event_id, media_id, parser_version,
                ocr_model, raw_text, status (pending|confirmed|rejected)
launch_metrics  1 球 = 1 行。列は §4.2.1
metric_edits    metric_id, field, before, after, edited_at   -- 訂正履歴

rounds          id, session_id, course, total, putts, fairways_hit, gir, penalties, source
holes           round_id, hole_no, par, strokes, putts, fw, gir, penalty

swing_analyses  id, media_id, method (pose|llm), version, keyframes_json, metrics_json,
                findings_text, created_at
                -- method と version を残し、解析手法を変えても過去と比較・再計算できる
```

#### 4.2.1 レッスン計測データ（`launch_metrics`）

サンプル（2026-11-21 受領）:

```
2026/10/07 17:09 7アイアン
飛距離: 149.9yd / キャリー: 131.4yd / ラン: 18.5yd
クラブスピード: 31.6m/s / ボールスピード: 44.3m/s / ミート率: 1.40（高い）
最高到達点: 15.7m / 落下角度: 33.1° / 左右のズレ: 左 6.5yd
打ち上げ角度(縦): 16.1° / バックスピン: 4449rpm（少ない）/ 打ち出し角度(横): 右 2.3°
サイドスピン: 857rpm（ドロー・左回転）/ クラブ軌道: 5.8°（In-Out）/ フェース角度: 右 1.9°（Opened）
```

**符号の規約: 右・オープン・イントゥアウトを正とする**（右打ち前提。左右の向きは打球方向から見た向き）。
画面の表記（「左」「In-Out」「Opened」など）は失わないよう、`labels_json` に原文のまま残す。
単位は画面の単位（yd / m/s / m / ° / rpm）のまま保存し、換算はクエリ側で行う。

| 列 | 画面の項目 | 単位 | サンプル値 | 正規化 |
|---|---|---|---|---|
| `shot_at` | 日時 | — | 2026-10-07 17:09 | JST の datetime。セッションの紐づけキーにもなる |
| `club` | クラブ | — | `7I` | 「7アイアン」→ `7I`、「ドライバー」→ `1W` などに正規化。原文は `labels_json` |
| `total_yd` | 飛距離 | yd | 149.9 | |
| `carry_yd` | キャリー | yd | 131.4 | |
| `run_yd` | ラン | yd | 18.5 | |
| `club_speed_mps` | クラブスピード | m/s | 31.6 | |
| `ball_speed_mps` | ボールスピード | m/s | 44.3 | |
| `smash_factor` | ミート率 | — | 1.40 | 評価（高い）は `labels_json.smash_factor` |
| `apex_m` | 最高到達点 | m | 15.7 | |
| `descent_angle_deg` | 落下角度 | ° | 33.1 | |
| `offline_yd` | 左右のズレ | yd | −6.5 | 左 = 負 |
| `launch_v_deg` | 打ち上げ角度(縦) | ° | 16.1 | |
| `backspin_rpm` | バックスピン | rpm | 4449 | 評価（少ない）は `labels_json.backspin` |
| `launch_h_deg` | 打ち出し角度(横) | ° | +2.3 | 右 = 正 |
| `sidespin_rpm` | サイドスピン | rpm | −857 | 左回転（ドロー）= 負。原文は `labels_json.sidespin` |
| `club_path_deg` | クラブ軌道 | ° | +5.8 | In-Out = 正 / Out-In = 負 |
| `face_angle_deg` | フェース角度 | ° | +1.9 | 右（Opened）= 正 / 左（Closed）= 負 |
| `face_to_path_deg` | （派生） | ° | −3.9 | `face_angle − club_path`。保存はせずビューで計算 |

その他の列: `id`, `capture_id`, `shot_no`, `labels_json`（画面の評価・方向の原文）,
`extra_json`（確定列に無い項目）, `confidence_json`（OCR 時のみ。項目ごとの信頼度）, `check_flags`（下記の検算結果）。

**取り込み時の検算**（テキスト・OCR 共通。どれかに当てはまる球は確認 Flex で注意表示し、確定前に人が見る）:

| 検算 | 式 | サンプル |
|---|---|---|
| 距離の整合 | `total ≈ carry + run`（±0.2yd） | 131.4 + 18.5 = 149.9 ✓ |
| ミート率の整合 | `smash ≈ ball_speed / club_speed`（±0.02） | 44.3 / 31.6 = 1.402 ✓ |
| 曲がりの向き | サイドスピンの符号と `face_to_path` の符号が一致 | 左回転（−）と −3.9° ✓ |
| 方向表記と符号 | 「左」「右」「In-Out」「Opened」などの表記と数値の符号が一致 | ✓ |
| 値の範囲 | クラブごとの妥当範囲（例: 7I の打ち上げ角 5〜35°） | ✓ |

分析では、クラブ別のキャリーのばらつき、`face_to_path` と `offline_yd` の関係、
練習メモ（例:「フェースが開く」）が書かれた前後の数値の変化などを扱う。

### 4.3 API

| エンドポイント | 公開 | 内容 |
|---|---|---|
| `POST /api/line/webhook` | Funnel で公開 | LINE webhook。署名検証・許可リスト・冪等保存 |
| `GET /healthz` | ローカルのみ | 死活監視 |
| `POST /admin/reprocess` | ローカルのみ（`APP_ENV=dev`） | 原本から派生データを再生成 |

#### 4.3.1 リッチメニューと入力モード

送る種類をリッチメニューで先に選び、その後に届いたメッセージを選んだ種類として扱う。
メニューは 6 ボタン（大サイズ 2500×1686 を 2 行 × 3 列）。各ボタンは postback で
`action=<名前>` を送る。メニュー画像と登録は `scripts/setup_richmenu.py` で行う（Messaging API）。

```
┌────────────┬────────────┬────────────┐
│  📝 メモ     │  📊 計測     │  🎥 動画     │
├────────────┼────────────┼────────────┤
│ ▶ 開始/終了  │  🏌 スコア   │  🔍 振り返り  │
└────────────┴────────────┴────────────┘
```

| ボタン | postback | 押したときの動作 | モード中に届いたものの扱い |
|---|---|---|---|
| 📝 メモ | `action=mode&mode=memo` | ほかのモードを解除してメモモードに戻す | テキストはメモ。モードなしのときの既定と同じ |
| 📊 計測 | `action=mode&mode=metrics` | 「計測テキストを貼ってください（30 分有効）」と返す | テキストを計測として解析。複数球は日時行で区切る。読めない行は行番号付きで返し、全く読めなければ「メモとして保存しますか？」と聞く。画像は OCR（Phase 2） |
| 🎥 動画 | `action=mode&mode=video` | Quick Reply で アングル（後方 / 正面）→ クラブ を選ばせ、「動画を送ってください」と返す | 動画を選んだアングル・クラブ付きで保存。続けて送った動画も同じ設定で保存 |
| ▶ 開始/終了 | `action=session` | セッションが無ければ Quick Reply で 練習 / レッスン / ラウンド を選んで開始（ラウンドはコース名を任意で送れる）。あれば「終了しますか？」 | — （モードではない） |
| 🏌 スコア | `action=mode&mode=score` | 「スコアを送ってください（例: 92 パット34 FW7/14 パーオン5）」と返す | テキストをスコアとして保存。Phase 1 は原文のまま保存し、抽出は Phase 2 で原本から行う |
| 🔍 振り返り | `action=mode&mode=ask` | Phase 3 までは「準備中」と返す。以降は「質問をどうぞ」 | テキストを分析エージェントへの質問として扱う |

モードの規則:

- モードは**最後の操作から 30 分**で自動解除し、メモモード（既定）に戻る。別のボタンを押せば切り替わる。
- 返信には毎回いまのモードとセッションを付ける（例: 「⛳ 7I 1 球を保存 ｜ 計測モード・レッスン中」）。
- セッションは「終了」を押すか、最終操作から 6 時間、または日付が変わったら自動で終了する。
  セッション中に届いたものはすべてそのセッションに紐づく。セッションが無いときは日付で仮のセッションを作る。

**ボタンを押さずに送った場合**（自動判定。取りこぼしを出さないための予備）:

| 届いたもの | 扱い |
|---|---|
| 計測テキスト（`YYYY/MM/DD HH:MM <クラブ>` の行と `キャリー:` などの項目を含む） | 計測として保存し、「計測として保存しました（違えば取消）」と返す |
| その他のテキスト | メモとして保存（Phase 2 から自動分類） |
| 動画 | 保存したうえで、Quick Reply でアングル・クラブを聞く（答えなくても保存は済んでいる） |
| 画像 | 保存したうえで、計測画像かどうかを Quick Reply で聞く。計測なら OCR（Phase 2） |

テキストのコマンド（メニューを使わない場合の代替）:

| 入力 | 動作 |
|---|---|
| `取消` | 直前の 1 件を論理削除 |
| `終了` | 入力モードとセッションを終了 |
| `? <質問>` | 分析エージェントに質問（Phase 3） |

### 4.4 主要モジュール

```
golf-notes-agent/
├ app/
│ ├ line/        webhook, 署名検証, reply/push, Flex / Quick Reply テンプレート, postback ルーティング
│ ├ modes/       入力モードとセッションの状態遷移 (input_modes / sessions, 自動解除)
│ ├ ingest/      raw_events 保存, media 取得, 取り込みフォルダ監視 (Phase 4)
│ ├ jobs/        SQLite キュー, ワーカー, リトライ
│ ├ enrich/      分類, セッション紐づけ, スコア抽出, レッスン計測の解析 / OCR
│ ├ swing/       キーフレーム抽出 (ffmpeg), 姿勢推定 (MediaPipe), 指標計算, 比較
│ ├ search/      ローカル embedding, sqlite-vec
│ ├ agent/       分析エージェントとツール定義 (sql_readonly, search_memos, get_metrics, compare_swings)
│ ├ storage/     DB リポジトリ, メディアの保存先
│ └ scheduler/   backup, 週次レポート
├ mcp/           golf-data MCP サーバ (読み取り専用)
├ migrations/    alembic
├ config/        local.env.example, tailscale-serve.json, richmenu/ (メニュー画像と定義)
├ scripts/       setup_richmenu.py (リッチメニューの作成・画像アップロード・既定設定)
├ docker-compose.yml
└ tests/
```

スイング解析の指標（Phase 4、後方・正面で別定義）:
頭の移動量、前傾角の変化、肩・腰の回転差（近似）、テンポ比（バックスイング : ダウンスイング）、
アドレス / トップ / インパクト / フィニッシュのキーフレーム。

### [必須] 4.5 Test Plan

- **Unit**: 署名検証、許可リスト、冪等キー、スコア文字列の抽出、計測テキストのパーサ（§4.2.1 のサンプルを固定入力、項目の順序違い・欠損・複数球・未知の行）→ `launch_metrics` の正規化（符号規約・クラブ名）、§4.2.1 の検算、
  入力モードとセッションの状態遷移（切替・30 分での自動解除・6 時間 / 日付変更での自動終了・モード中に読めないテキスト・ボタンなしの自動判定）、
  スイング指標の計算（固定のキーポイント列を入力）
- **Integration**: webhook → raw_events → jobs → media 保存までを LINE API をモックして通す。
  postback（各ボタン）→ モード設定 → 後続メッセージの保存先が正しいこと。
  リトライと失効時の通知。SQLite のバックアップ・復元
- **Golden**: §4.2.1 のサンプルテキストを固定入力にし、全項目が期待値と一致すること。OCR は画像サンプルを入手したら同様に追加。
  モデル・プロンプト変更時の回帰検知に使う
- **Manual**: 実機の LINE で 6 ボタンすべてと各メッセージ種別を送信、Funnel 経由で届くことを確認。月 1 で復元リハーサル
- カバレッジ 80% 以上（LLM 呼び出し部はモック）

### [推奨] 4.6 Migration / Rollback

新規モジュールのため移行なし。派生データは `POST /admin/reprocess` で原本から再生成できるので、
分類・計測解析・OCR・動画解析ロジックの変更は「新バージョンで再生成 → 比較 → 切替」でロールバック可能。

### [推奨] 4.7 Feature Enablement

フェーズごとに env フラグで有効化する（`ENABLE_CLASSIFY` / `ENABLE_LESSON_METRICS` / `ENABLE_LESSON_OCR` / `ENABLE_AGENT` /
`ENABLE_SWING_ANALYSIS`）。Phase 1 の保存機能はフラグなしで常に有効。

---

## [推奨] 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform（ローカル JSONL）に `memo_ingested` / `media_saved` / `job_failed` /
  `lesson_metrics_saved` / `llm_call`（費用・トークン）を emit
- Healthchecks.io への ping で死活監視（PROPOSAL-0013 と同じ）

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| LINE の「検証」が失敗する | Funnel 無効 / sidecar 停止 / パス違い。`tailscale funnel status` を確認 |
| 動画が保存されない | 変換待ちのタイムアウト。`jobs` の `last_error` を確認し、`fetch_media` を再実行 |
| 計測値の項目が欠ける・ずれる | 計測テキストの書式変更。`extra_json` に入った行を確認し、パーサを更新して原本から再解析 |

### 5.3 Dependencies

Tailscale (Funnel)、line-bot-sdk v3、Claude API（llm-gateway / llm-client）、ffmpeg、MediaPipe、
sqlite-vec、ローカル embedding モデル（多言語対応のもの）、analytics-platform (path dep)

### [推奨] 5.4 Non-Functional Requirements

#### 性能 (Performance)
webhook は 1 秒以内に 200 を返す。保存確認の返信は 10 秒以内、計測テキストの保存返信は 10 秒以内、OCR の確認 Flex は 30 秒以内。

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

### 案 C: リッチメニューを使わず、届いた内容から種類を自動判定する
操作は最も少ないが、書式が崩れた計測テキストとメモの区別があいまいになり、動画のアングル・クラブや
セッションの区切りは推測に頼ることになる。リッチメニューで先に選ぶ方式を主経路とし、
自動判定は押し忘れたときの予備として残す（§4.3.1）。

### 案 D: Postgres + pgvector をローカルで動かす
機能的には十分だが、自分専用・単一プロセスの規模では SQLite + sqlite-vec の方が運用・バックアップが単純。
将来 GCP に移す場合は PROPOSAL-0013 の db_copy 方式で移行できる。

## [必須] 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-11-21 | Draft | 初稿 |
| 2026-11-21 | Draft | 送る種類をリッチメニューで先に選ぶ方式を主経路に（自動判定は予備）。リッチメニュー・入力モード・計測テキスト解析を Phase 1 に前倒し（§4.3.1） |
| 2026-11-21 | Draft | 計測データはテキストで取得できると判明。取り込みの主経路をテキスト解析（LLM 不要）にし、OCR は補完に変更 |
| 2026-11-21 | Draft | レッスン計測サンプル受領。`launch_metrics` の列・符号規約・検算を確定（§4.2.1） |

### 実装フェーズ

| Phase | 内容 | 完了条件 |
|---|---|---|
| 1 MVP | webhook・許可リスト・冪等保存・media 取得・取消・バックアップ・Funnel・**リッチメニューと入力モード・セッション開始/終了**・**計測テキストの解析（ルールベース）** | 1 か月使って取りこぼしゼロ。計測値とセッションが正しく紐づいてたまる |
| 2 | メモの自動分類（LLM）・計測画像の OCR・スコア抽出（Phase 1 で保存した原文から）・スコアカード写真 | スコアが確定データとしてたまる |
| 3 | ローカル embedding・LINE での QA・週次レポート・MCP サーバ | 根拠付きで質問に答えられる |
| 4 | スイング解析（姿勢推定・キーフレーム所見・時系列比較）・取り込みフォルダ | 同アングル動画の変化を数値と言葉で返せる |
| 5 | スコアアプリ CSV 取り込み（可能なら）・次の練習テーマの自律提案 | — |
