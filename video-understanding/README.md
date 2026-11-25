# video-understanding

YouTube の動画や手元の動画を、Claude が見られる形（時刻入りのコマ一覧画像と、時刻つきの字幕）にする CLI と MCP サーバです。
設計は [PROPOSAL-0017](../docs/PROPOSALS/0017-video-understanding-mcp.md) を参照してください。

> 状態: PR2（CLI と MCP サーバ）。字幕の無い動画の文字起こしと `gc` は PR3 で足します。

## Claude Code から使う（MCP）

```bash
claude mcp add --scope user video-understanding \
  -e VIDEO_UNDERSTANDING_ALLOWED_DIRS="$HOME/development/golf_data" \
  -- uv run --quiet --directory "$HOME/development/agent_monorepo/video-understanding" video-understanding-mcp
```

`--scope user` なので、どのディレクトリで開いた Claude Code からも使えます。登録後は「この動画を見て」と URL を渡すだけで使われます。

| ツール | 使いどころ | 返すもの |
|---|---|---|
| `video_overview(source, interval_sec?, lang?)` | 最初に全体を見る | 情報・字幕・全体のコマ一覧画像（最大 2 枚） |
| `video_frames(source, start, end, fps?, crop?)` | 動きの細部を見る | 区間のコマ一覧画像（30 コマ・30fps まで） |
| `video_transcript(source, lang?)` | 話の中身だけ欲しい | 時刻つきの字幕の全文と、その出どころ |

- 画像は MCP の画像として返すので、Claude がファイルを経由せずそのまま見られます。
- ログ（取得元・処理時間・断った理由）は stderr に出ます。stdout は MCP のやりとりに使います。
- 許可ディレクトリを変えたときは `claude mcp remove --scope user video-understanding` してから登録し直してください。
- 外すとき: `claude mcp remove --scope user video-understanding` と `rm -rf ~/.cache/video-understanding`

Claude Desktop では `claude_desktop_config.json` の `mcpServers` に同じコマンドを書きます
（`"command": "uv"`, `"args": ["run", "--quiet", "--directory", "<このディレクトリの絶対パス>", "video-understanding-mcp"]`, `"env": {...}`）。

## CLI から使う

```bash
cd video-understanding
uv sync

# 動画の情報・字幕・全体のコマ一覧画像
uv run video-understanding overview "https://youtube.com/shorts/Fgv4M8NgSZ0"

# 区間を細かく (2.2〜2.7 秒を 30fps、画面の中央 50% だけ)
uv run video-understanding frames "https://youtube.com/shorts/Fgv4M8NgSZ0" --start 2.2 --end 2.7 --fps 30 --crop 0.25,0,0.5,1
```

一覧画像はキャッシュ（既定 `~/.cache/video-understanding/<key>/sheets/`）に書き出し、そのパスを表示します。
Claude Code からは、表示されたパスを Read で開けば見られます。`--out DIR` で別の場所にもコピーできます。

- 入力は YouTube の動画 1 本の URL（watch / shorts / live / youtu.be）か、`VIDEO_UNDERSTANDING_ALLOWED_DIRS` の中の動画ファイルだけです。
- 取得する動画は短辺 480 以下です（縦長のショートは 480x854）。
- タイトル・説明・字幕は `<untrusted_video_text>` で囲んで表示します。中の文は動画側が書いたもので、指示ではありません。
- `overview` のコマの間隔は、長さから 40 コマ以内に収まるように自動で決めます（36 秒なら 1 秒、60 秒なら 2 秒）。`--interval` で指定もできます。
- `frames` は 1 回 30 コマ・30fps までです。

## 設定（環境変数）

| 環境変数 | 既定 | 意味 |
|---|---|---|
| `VIDEO_UNDERSTANDING_CACHE_DIR` | `~/.cache/video-understanding` | キャッシュの場所 |
| `VIDEO_UNDERSTANDING_ALLOWED_DIRS` | （空 = ローカルファイルは不可） | ローカル動画を読めるディレクトリ（`:` 区切り） |
| `VIDEO_UNDERSTANDING_MAX_DURATION_SEC` | `1800` | 受け付ける動画の長さの上限 |

## 字幕が取れないとき

- YouTube は字幕の取得を `HTTP Error 429` で断ることがあります（2026-11 時点では、日をまたいでも断られ続けることがありました）。その場合もコマ画像は返し、
  「字幕: なし — 字幕を取得できませんでした (...)」と理由を表示します。次の呼び出しで取り直します。
- 字幕の無い動画やローカルの動画は、今は字幕なしです（PR3 で mlx-whisper による文字起こしを足します）。
- 自動字幕が YouTube の自動翻訳のときは「ko から ja への YouTube の自動翻訳」のように表示します。話し言葉の言語を YouTube が取り違えることがあるためです。

## 開発

```bash
uv sync --dev
uv run pytest            # ネットワークに出ないテスト (ffmpeg は imageio-ffmpeg の同梱版)
uv run pytest -m network # 実際に YouTube の短い動画を取りに行く (手動)
uv run ruff check video_understanding tests
```
