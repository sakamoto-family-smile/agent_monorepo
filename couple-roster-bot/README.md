# couple-roster-bot

夫婦で使う名簿管理システム。**LINE**（トーク / LIFF フォーム）を入口に、**Google スプレッドシート**へ名前・住所・家族の間柄を登録・検索できます。**CSV 一括インポート**と**写真からの OCR 読み取り**にも対応します。

- 設計の詳細と構成図: [`docs/design.md`](docs/design.md)
- スタック: Python 3.12 / FastAPI / Cloud Run / line-bot-sdk v3 / gspread
  （本モノレポの他 LINE Bot と統一）

## できること

| 入口 | 操作 |
|---|---|
| LIFF フォーム | 名前・住所・間柄（プルダウン）を入力して登録。郵便番号→住所の自動補完 |
| トーク | `検索 山田` / `一覧` / `ヘルプ` |
| CSV ファイル送信 | 検証・重複チェック → プレビュー →「確定」で一括登録 |
| 画像送信 | 名刺・封筒を OCR → 抽出 → 確認フォームで保存 |

## アーキテクチャ概要

```
LINE ─┬─(webhook)─▶ FastAPI (Cloud Run) ─▶ Google スプレッドシート
      └─(LIFF)────▶  ├─ RosterService（登録/検索/更新/削除）
                      ├─ csv_import（一括取り込み）
                      └─ ocr（Drive / Vision + 項目抽出）
```

データアクセスは `RosterRepo` プロトコルに集約。`storage_mode` で in-memory /
スプレッドシートを切り替え、将来は Firestore / Cloud SQL 実装に差し替え可能です。

```
app/
├── main.py              # FastAPI エントリポイント（/health, /webhook, /liff, /api/*）
├── config.py            # pydantic-settings（COUPLE_ROSTER_* env）
├── models.py            # RosterEntry / Relation / EntryDraft（検証）
├── line_client.py       # LINE v3 SDK ラッパ（署名検証・reply・content 取得）
├── deps.py              # DI（repo / service / ocr / 保留インポート）
├── routes/
│   ├── line.py          # POST /webhook（text / csv / image）
│   └── liff.py          # GET /liff, /api/relations, /api/entries, POST /api/entries
├── repositories/
│   ├── protocols.py     # RosterRepo（Protocol）
│   ├── in_memory.py     # テスト / 開発用
│   └── sheets.py        # Google スプレッドシート実装
├── services/
│   ├── roster.py        # 業務ロジック（検証・重複・CRUD・検索）
│   ├── csv_import.py    # CSV 解析・検証・重複・プレビュー
│   ├── messages.py      # LINE 返信テキスト整形
│   ├── ocr.py           # 項目抽出（純粋関数）+ エンジン抽象
│   ├── ocr_drive.py     # Google Drive OCR（無料）
│   └── ocr_vision.py    # Cloud Vision OCR（高精度）
└── ui/form.html         # LIFF 入力フォーム
```

## セットアップ

```bash
make install      # uv sync --dev
make test         # pytest（59 ケース）
make lint         # ruff
make run          # ローカル起動（storage=memory / ocr=mock）
```

`make run` は env なしでも起動し、`GET /health` と `GET /liff`、`/api/*` が動きます
（LINE webhook は `LINE_*` 未設定だと 503）。

## 環境変数

`.env.example` をコピーして `.env` を作成します（すべて `COUPLE_ROSTER_` プレフィックス）。

| 変数 | 説明 |
|---|---|
| `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API |
| `ALLOW_ALL_USERS` / `ALLOWED_LINE_USER_IDS` | 認可（本番は false + 夫婦 2 名の userId） |
| `STORAGE_MODE` | `memory`（既定）/ `sheets` |
| `SPREADSHEET_ID` / `WORKSHEET_NAME` | 対象スプレッドシート |
| `GOOGLE_CREDENTIALS_PATH` | サービスアカウント鍵。空なら ADC |
| `OCR_PROVIDER` | `mock`（既定）/ `drive` / `vision` |
| `LIFF_ID` / `PUBLIC_BASE_URL` | LIFF とフォーム URL 生成 |

## スプレッドシート準備（storage=sheets）

1. Google スプレッドシートを新規作成し、その ID を `SPREADSHEET_ID` に設定。
2. サービスアカウントを作成し、そのメールアドレスをスプレッドシートに**編集者**で共有。
3. `--extra sheets` を有効化（`uv sync --extra sheets`）。
4. 1 行目のヘッダ（`id,name,kana,zip,address,relation,note,created_by,created_at,updated_at`）は
   ワークシート未作成時に自動生成されます。

## デプロイ（Cloud Run）

```bash
DOCKER_BUILDKIT=1 docker build -f couple-roster-bot/Dockerfile \
  -t couple-roster-bot:local couple-roster-bot
```

イメージは既定で `sheets` + `ocr-drive` extra を含みます。Cloud Run のサービス
アカウントに Sheets / Drive のスコープを付与し、env を設定してデプロイします。
LINE Developers 側で Webhook URL を `https://<cloud-run-url>/webhook`、
LIFF エンドポイントを `https://<cloud-run-url>/liff` に設定します。

## テスト

純粋ロジック（models / csv_import / roster / ocr / messages）を pytest で網羅
しています。クラウド依存（Sheets / Drive / Vision）は Protocol / 遅延 import で
分離し、テストは外部接続なしで完結します。

```bash
make test
```

## セキュリティ

- Webhook は `X-Line-Signature`（HMAC-SHA256）を検証
- 認可されていない LINE ユーザーは無視（ホワイトリスト）
- シークレットは env / Secret Manager 管理。鍵ファイルはコミットしない
- OCR の一時ドキュメントは処理後に削除（画像を残さない）
