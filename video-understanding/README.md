# video-understanding

YouTube の動画や手元の動画を、Claude が見られる形（時刻入りのコマ一覧画像と、時刻つきの字幕）にする CLI と MCP サーバです。
設計は [PROPOSAL-0017](../docs/PROPOSALS/0017-video-understanding-mcp.md) を参照してください。

## 準備

```bash
cd video-understanding
uv sync --extra whisper   # 文字起こしも使う (Apple Silicon の Mac のみ。torch などが入り .venv は約 1.3GB)
# uv sync                 # 字幕とコマ画像だけでよいとき
```

文字起こしのモデル（whisper-large-v3-turbo、約 1.6GB）は、初めて文字起こしするときに Hugging Face から取得します（`~/.cache/huggingface/`）。

## Claude Code から使う（MCP）

```bash
claude mcp add --scope user video-understanding \
  -e VIDEO_UNDERSTANDING_ALLOWED_DIRS="$HOME/development/golf_data" \
  -- uv run --quiet --extra whisper --directory "$HOME/development/agent_monorepo/video-understanding" video-understanding-mcp
```

`--extra whisper` を付けておくと、開発中に `uv sync`（extra なし）で mlx-whisper が外れても、起動のたびに入れ直されます。
文字起こしを使わないときは外してください。

`--scope user` なので、どのディレクトリで開いた Claude Code からも使えます。登録後は「この動画を見て」と URL を渡すだけで使われます。

| ツール | 使いどころ | 返すもの |
|---|---|---|
| `video_overview(source, interval_sec?, lang?)` | 最初に全体を見る | 情報・字幕・全体のコマ一覧画像（最大 2 枚） |
| `video_frames(source, start, end, fps?, crop?)` | 動きの細部を見る | 区間のコマ一覧画像（30 コマ・30fps まで） |
| `video_transcript(source, lang?, force_whisper?)` | 話の中身だけ欲しい | 時刻つきの字幕か文字起こしの全文と、その出どころ |

- 画像は MCP の画像として返すので、Claude がファイルを経由せずそのまま見られます。
- ログ（取得元・処理時間・断った理由）は stderr に出ます。stdout は MCP のやりとりに使います。
- 許可ディレクトリを変えたときは `claude mcp remove --scope user video-understanding` してから登録し直してください。
- 外すとき: `claude mcp remove --scope user video-understanding` と `rm -rf ~/.cache/video-understanding`

Claude Desktop では `claude_desktop_config.json` の `mcpServers` に同じコマンドを書きます
（`"command": "uv"`, `"args": ["run", "--quiet", "--extra", "whisper", "--directory", "<このディレクトリの絶対パス>", "video-understanding-mcp"]`, `"env": {...}`）。

## CLI から使う

```bash
# 動画の情報・字幕・全体のコマ一覧画像
uv run video-understanding overview "https://youtube.com/shorts/Fgv4M8NgSZ0"

# 区間を細かく (2.2〜2.7 秒を 30fps、画面の中央 50% だけ)
uv run video-understanding frames "https://youtube.com/shorts/Fgv4M8NgSZ0" --start 2.2 --end 2.7 --fps 30 --crop 0.25,0,0.5,1

# 字幕か文字起こしの全文 (--force-whisper で字幕があっても文字起こしする)
uv run video-understanding transcript "https://youtube.com/shorts/Fgv4M8NgSZ0"

# 最終利用から 14 日を過ぎた動画本体・コマを消す (情報・字幕・文字起こしは残す)
uv run video-understanding gc --dry-run
uv run video-understanding gc
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
| `VIDEO_UNDERSTANDING_VIDEO_TTL_DAYS` | `14` | `gc` で動画本体・コマを消すまでの日数（最終利用から） |
| `VIDEO_UNDERSTANDING_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | 文字起こしのモデル |
| `VIDEO_UNDERSTANDING_WHISPER_PROMPT` | ゴルフ用語の一覧 | 文字起こしの用語ヒント（空にするとヒント無し） |

## 字幕と文字起こし

- YouTube は字幕の取得を `HTTP Error 429` で断ることがあります（2026-11 時点では、日をまたいでも断られ続けることがありました）。その場合もコマ画像は返し、
  「字幕: なし — 字幕を取得できませんでした (...)」と理由を表示します。次の呼び出しで取り直します。
- 字幕が無いとき（取得に失敗したとき・ローカルの動画を含む）は、音声を mlx-whisper で文字起こしします。
  結果はキャッシュに残すので、2 回目からはすぐ返ります（モデルか用語ヒントを変えると取り直します）。
- 音声が無い動画（SMART GOLF のスイング動画など）や無音の動画は、文字起こしせずに理由を表示します。
- BGM の歌しか入っていない動画では、歌詞が文字起こしされます。テロップはコマ画像から読んでください。
- `video_frames` は文字起こしをしません。
- 自動字幕が YouTube の自動翻訳のときは「ko から ja への YouTube の自動翻訳」のように表示します。話し言葉の言語を YouTube が取り違えることがあるためです。

## 開発

```bash
uv sync --dev
uv run pytest            # ネットワークに出ないテスト (ffmpeg は imageio-ffmpeg の同梱版)
uv run pytest -m network # 実際に YouTube の短い動画を取りに行く (手動)
uv run ruff check video_understanding tests
```
