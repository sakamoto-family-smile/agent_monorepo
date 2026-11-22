# golf-notes-agent

練習・レッスン・ラウンドのメモ、スイング動画、レッスンの計測結果を LINE で送るだけで Mac mini に貯める、自分専用のサービス。
設計は [PROPOSAL-0016](../docs/PROPOSALS/0016-golf-notes-agent.md)。いまは Phase 1（受信と保存。LLM は使わない）。

## できること（Phase 1）

リッチメニュー（6 ボタン）で送る種類を先に選ぶ。押さずに送っても保存はされる。

| ボタン / 送るもの | 動き |
|---|---|
| 📝 メモ / テキスト | `memos` に保存。「📝 メモを保存しました ｜ 11/22 の練習（仮）」 |
| 🎥 動画 | アングル（後方 / 正面）→ クラブを選ぶと、30 分の間に送った動画にそれを付けて保存 |
| 動画・画像（ボタンなし） | 保存してから、動画はアングル・クラブ、画像は計測画像かどうかを Quick Reply で聞く |
| ▶ 開始/終了 | 練習 / レッスン / ラウンドを開始。ラウンドはコース名を送る（最近のコースは Quick Reply）。開いていれば終了 |
| 🏌 スコア | 30 分の間に送ったテキストをスコアの原文として `score_texts` に保存（集計は Phase 2） |
| 📊 計測 | 30 分の間に貼った計測テキストを読み取り、1 球 1 行で `launch_metrics` に保存（LLM は使わない）。検算に引っかかった球は「確定 / 取消」を聞く。入れ先のセッションは計測の日時で決め、「付け替え」で選び直せる |
| 計測テキスト（ボタンなし） | 日時とクラブの行と「キャリー:」があれば計測として保存し、「違えば取消」と返す |
| 🔍 振り返り | 準備中（Phase 3） |
| `取消` / `終了` | 直前のメモ・動画・画像・スコアを論理削除 / 入力モードとセッションを終了 |

- 入力モードは最後の操作から 30 分で切れる。返事の末尾にいまのモードとセッションを出す。
- セッションは終了ボタンか、最終操作から 6 時間で終わる（日付では切らない）。ボタンを押さずに送ったものはその日の仮のセッション（練習）に入る。
- 動画・画像の原本は `data/media/YYYY/MM/<sha256>.<ext>`。取得に失敗したときだけ push で知らせる。
- 届いたイベントはすべて原本として `data/raw/YYYY/MM/<webhookEventId>.json` と `raw_events` に残す。
  同じ webhookEventId（LINE の再送・ボタンの連打）は 2 回目以降を保存しない。
- 許可リスト（`ALLOWED_USER_IDS`）にない userId からのイベントは、保存も返事もしない。

## 構成

```
app/
├ main.py        FastAPI の組み立て。起動時にマイグレーションし、同じプロセスでジョブのワーカーと定期処理を動かす
├ webhook.py     POST /api/line/webhook (署名検証 → 許可リスト → 原本の保存 → 処理 → reply)
├ handlers/      イベントごとの保存と返事 (dispatch: メッセージ / postback: ボタン / lesson: 計測)
├ lesson/        計測テキストの読み取り (parser) と検算 (checks)
├ line/          署名検証・イベントの読み取り・Messaging API
├ jobs/          ジョブキュー (golf.db の jobs)・ワーカー・動画と画像の取得
├ storage/       テーブル定義・原本・セッション・入力モード・コース・メモ・動画
├ push.py        push の送信と月の通数の上限
├ scheduler.py   定期処理 (日次バックアップ・死活監視の ping)
├ backup.py      golf.db の .backup と世代管理
└ reprocess.py   原本から作り直す CLI
migrations/      Alembic (golf.db)。分析では確定した計測だけを含むビュー v_launch_metrics (face_to_path_deg 付き) を使う
```

## ローカルで動かす（Mac mini）

事前準備:

1. LINE Developers で golf-notes 専用の Messaging API チャンネルを作る（既存の Bot とは共有しない）。
   応答メッセージ・あいさつメッセージは OFF、Webhook の再送は ON にする
2. `cp config/local.env.example config/local.env` して、チャンネルシークレット・アクセストークン・自分の userId を書く
3. `cp config/tailscale.env.example config/tailscale.env` して、Tailscale の auth key を書く
   （stock-analysis-agent とは別のノードになり、ホスト名は `golf-notes`）

```bash
make up            # backend + Funnel
make logs
curl -fsS http://127.0.0.1:8002/healthz
```

リッチメニューを登録する（メニューを変えたときも同じ）:

```bash
uv run --with pillow python scripts/make_richmenu_image.py   # 画像を作り直すときだけ
uv run python scripts/setup_richmenu.py                      # config/local.env のトークンで登録し、既定にする
```

LINE の Webhook URL は `https://golf-notes.<tailnet>.ts.net/api/line/webhook`。LINE Developers の「検証」で 200 が返ることを確かめる。

### データ

`./data`（`GOLF_DATA_DIR` で変更可）に `golf.db`・`raw/`・`media/`・`backup/` を置く。
**golf.db をホストの macOS から直接開かない**（Docker Desktop の VM の中で書き込み中の WAL を壊す恐れがある）。
中身を見るときは `make sh-db`（コンテナの中で読み取り専用で開く）。

### バックアップ

- backend が毎日 3 時以降に `data/backup/golf-YYYYMMDD.db` を作る（SQLite の backup API。整合性を確かめてから置き、14 世代残す）。
  Mac mini が止まっていて過ぎた分は起動後に作る。失敗したら push と Healthchecks.io の /fail で知らせる。今すぐ作るときは `make backup-now`
- 外部 SSD へは `data/backup/`・`raw/`・`media/` だけを rsync する（golf.db 本体はコピーしない）:

  ```bash
  GOLF_OFFSITE_DIR=/Volumes/<SSD>/golf-notes make offsite           # 1 回
  GOLF_OFFSITE_DIR=/Volumes/<SSD>/golf-notes make offsite-install   # launchd で毎日 4:30
  ```

- 復元: backend を止め、`data/backup/golf-YYYYMMDD.db` を `data/golf.db` に置き換えて（`golf.db-wal`・`-shm` は消す）起動する。
  その日のバックアップ以降の分は `make reprocess KIND=raw` で原本から raw_events に戻せる

### 原本から作り直す

```bash
make reprocess KIND=lesson DRY_RUN=1   # 計測テキストをいまのパーサで読み直したときに変わるものを表示
make reprocess KIND=lesson             # 置き換える (取り消した計測はそのまま)
make reprocess KIND=raw                # data/raw/ にあって DB に無い原本を取り込む
```

### 死活監視

`config/local.env` の `HEALTHCHECK_PING_URL` に Healthchecks.io の URL を入れると、5 分おきに ping する（Period 5 分・Grace 15 分くらい）。

## テスト

```bash
make test
```
