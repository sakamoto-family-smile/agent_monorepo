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
| 📊 計測・🔍 振り返り | 準備中（計測は PR3、振り返りは Phase 3） |
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
├ main.py        FastAPI の組み立て。起動時にマイグレーションし、同じプロセスでジョブのワーカーを動かす
├ webhook.py     POST /api/line/webhook (署名検証 → 許可リスト → 原本の保存 → 処理 → reply)
├ handlers/      イベントごとの保存と返事 (dispatch: メッセージ / postback: ボタン)
├ line/          署名検証・イベントの読み取り・Messaging API
├ jobs/          ジョブキュー (golf.db の jobs)・ワーカー・動画と画像の取得
├ storage/       テーブル定義・原本・セッション・入力モード・コース・メモ・動画
└ push.py        push の送信と月の通数の上限
migrations/      Alembic (golf.db)
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

## テスト

```bash
make test
```
