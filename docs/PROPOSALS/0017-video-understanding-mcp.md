# PROPOSAL-0017: YouTube などの動画を Claude Code が「見て・聞いて」理解するための video-understanding（CLI + MCP）

| | |
|---|---|
| **Status** | Implementing |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-11-23 |
| **Updated** | 2026-11-25 |
| **Target** | video-understanding（新規 cross-agent ツール） |
| **Related PRs** | #287 (設計), #288 (PR1) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## [必須] 1. Summary

Claude Code が YouTube などの動画の中身を、人が見るのに近い形で把握できるようにする。
具体的には、動画の情報（タイトル・説明・チャプター）、字幕（字幕が無ければ音声の文字起こし）、
時刻入りのコマ一覧画像を返すツール `video-understanding` をモノレポ直下に新設する。

本体は Python の CLI（ライブラリ）とし、薄い MCP サーバ（fastmcp、stdio）で包んで Claude Code / Claude Desktop から呼べるようにする。
処理はすべて Mac 上で完結させ、外部の LLM API は使わない。
入力は YouTube の URL と、許可したディレクトリ内のローカル動画（SMART GOLF のスイング動画など）の両方を受け付ける。

## [必須] 2. Motivation

- 2026-11-23 のスイング分析で、参考になりそうな YouTube ショート（比嘉兄弟のゴルフチャンネル）を Claude Code に渡したが、
  取得できたのはタイトル・サムネイル・自動抽出の 3 コマだけだった。
  説明文は空で、音声の説明も途中の動きも見られず、内容を人に補足してもらう必要があった。
- 動画の中身は、音声（話していること）・画面上の文字（テロップ）・動きの 3 つに分かれる。
  字幕と、時刻つきのコマ画像の 2 つがあれば、Claude はこの 3 つをほぼ把握できる（テロップはコマ画像から直接読める）。
- その場しのぎで `curl` やサムネイルを使う方法では、毎回やり方が変わり、結果も再現できない。
- 同じ部品（コマ抜き・一覧画像・文字起こし）は、golf-notes-agent の Phase 4（スイング解析、PROPOSAL-0016）や、
  レッスン動画の取り込みにも使える。

### [必須] 2.1 Goals

- [ ] YouTube の URL（通常の動画・ショート）を渡すと、1 回の呼び出しで「動画の情報＋字幕（または文字起こし）＋時刻入りのコマ一覧画像」が返る
- [ ] 指定した区間（例: 3.0〜5.0 秒）のコマを細かく（最大 30fps）取り出し、画像として返せる
- [ ] 字幕の無い動画でも、Mac 上の文字起こし（mlx-whisper）で日本語の音声を時刻つきテキストにできる
- [ ] ローカルの動画ファイル（許可したディレクトリ内）にも同じツールが使える
- [ ] 同じ動画を 2 回目に調べるときは、キャッシュから数秒で返る

### [必須] 2.2 Non-Goals

- 動画の要約や解釈をツール側でやること（解釈は呼び出した Claude が行う。ツールは素材を返すだけ）
- 姿勢推定・スイング指標の計算（golf-notes-agent の Phase 4 の範囲。必要ならそちらから本ツールのコマ抜きを使う）
- 長尺動画（目安 30 分超）の全編の処理（区間指定での利用に限る）
- ログインが必要な動画・限定公開の動画・ライブ配信
- 取得した動画の再配布や、どこかでの公開
- YouTube 以外のサイトへの対応（初期は YouTube とローカルファイルのみ。対象を広げる場合は提案を更新する）

---

## [必須] 3. Proposal

### [推奨] 3.1 User Stories

#### 3.1.1 参考動画の中身を確かめる
> スイング分析の途中で、YouTube ショートの URL を Claude Code に貼る。
> Claude は `video_overview` を呼び、字幕（または文字起こし）と 1 秒ごとのコマ一覧を見て、
> 「トップからいきなり腰を回すと起き上がるので、まず左足に体重を乗せてから回す」といった内容を、
> 何秒目にどの動きをしているかと合わせて説明する。人が補足しなくて済む。

#### 3.1.2 自分のスイングと参考動画を並べる
> `video_frames` で参考動画の切り返し区間（例: 2.0〜3.0 秒）を細かく取り出し、
> 自分の `golf_data/<shot>/Side.mp4` の同じ局面と並べて、腰の位置の違いを比べる。

### [推奨] 3.2 Notes / Constraints / Caveats

- **利用規約**: YouTube の利用規約は、公式機能以外でのダウンロードを原則禁止している。
  本ツールは「自分が見て内容を理解する」用途に限り、取得するのは低画質（既定 短辺 480 以下）の動画と字幕だけにする。
  キャッシュは手元にだけ置き、一定期間で消す（§4.2）。再配布はしない。
- **yt-dlp は YouTube 側の変更で動かなくなることがある**。依存のバージョンを固定せず、`uv lock --upgrade-package yt-dlp` で更新できるようにしておく。
- **画像は Claude の読み取り量（トークン）を多く使う**。一覧画像は 1 枚に最大 20 コマ、長辺 1568px 以下にまとめる。
  まず全体を粗く見て（`video_overview`）、必要な区間だけ細かく取る（`video_frames`）2 段構えにする。
- **文字起こし（mlx-whisper）は Apple Silicon でしか速く動かない**。ホストの Mac で動かす前提で、Docker には載せない。
  モデル（whisper-large-v3-turbo、約 1.6GB）は初回に Hugging Face から取得する。
- **ffmpeg は Homebrew ではなく `imageio-ffmpeg`（ffmpeg の実行ファイルを同梱した Python パッケージ）で入れる**。
  `uv sync` だけで環境がそろい、ほかのマシンでも同じ版になる。
  PR1 で確認済み（2026-11-24）: macOS arm64 版の ffmpeg 9.0 が入っており、コマ抜き・yt-dlp の映像と音声の結合・AV1 の読み込み・16kHz への変換が動く。
  ffprobe は入っていないため、長さ・大きさは ffmpeg の読み込みの先頭（`imageio_ffmpeg.read_frames` のメタ情報）から取る。
- **yt-dlp は YouTube から取るときに JavaScript の実行環境（deno）を求めるようになっている**（2026-11 時点）。
  無くても短辺 480 以下の形式は取れることを確認した（「一部の形式が取れないかもしれない」という注意は出る）。
  PyPI の `deno` を入れて試すと、今の組み合わせではかえって失敗したため、PR1 では入れない。
- **YouTube は字幕の取得を `HTTP Error 429` で断ることがある**（短時間に何度も取ったとき等）。yt-dlp 自身の字幕取得でも同じだった。
  ブラウザのふりをして制限を避ける方法（curl_cffi による偽装）は、相手の制限をかいくぐることになるので採らない。
  字幕が取れなくてもコマ画像は返し、理由を表示して次の呼び出しで取り直す。確実に内容を取るのは PR3 の文字起こしで補う。

### [必須] 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 字幕・説明文に、Claude への指示のような文が仕込まれている（プロンプトインジェクション） | High | ツールの戻り値で、字幕・説明文を「外部の動画から取ったデータ」と明示した枠に入れる（`<untrusted_video_text>` で囲む）。ツールは読み取りだけで、ファイルの書き込みはキャッシュディレクトリだけにする |
| 任意の URL・パスを渡され、意図しないサイトへのアクセスやファイルの読み出しが起きる | High | URL は `youtube.com` / `youtu.be` / `m.youtube.com` のみ許可。ローカルパスは `VIDEO_UNDERSTANDING_ALLOWED_DIRS` に入っているディレクトリの下だけ許可（`realpath` で解決してから判定し、シンボリックリンクでの抜け道を防ぐ）。どちらもテストで確かめる |
| 利用規約に反する使い方（大量取得・再配布） | Medium | 取得は 1 回の呼び出しで 1 本だけ。プレイリスト・チャンネル単位の取得は受け付けない。キャッシュの動画本体は既定 14 日で消す |
| 長い動画でディスク・時間を使いすぎる | Medium | 既定で 30 分を超える動画は断る（区間だけを取る機能は必要になったら足す）。動画は短辺 480 以下・音声は 16kHz モノラルで持つ |
| yt-dlp が壊れて取得できない | Low | エラーを「yt-dlp の更新が必要かもしれない」と分かる文で返す。ローカルファイルの処理は影響を受けない |
| 文字起こしの誤り（ゴルフ用語の聞き間違い） | Low | 文字起こしであることと、使ったモデルを戻り値に必ず書く。用語の一覧を `initial_prompt` に渡して精度を上げる（設定で変えられるようにする） |

---

## [必須] 4. Design Details

### 4.1 アーキテクチャ概略

```
Claude Code / Claude Desktop
   │  stdio（MCP）                       ターミナル（人・スクリプト）
   ▼                                         │
┌────────────── video-understanding（ホストの Mac 上） ──────────────┐
│ server.py  fastmcp: video_overview / video_frames / video_transcript │
│ cli.py     同じ機能を CLI で: overview / frames / transcript / gc     │
│   └──────────────┬──────────────────────────────────────────────────┘
│                  ▼
│  source.py     入力の判定（YouTube URL / 許可ディレクトリ内のファイル）
│  fetch.py      yt-dlp（Python API）で情報・字幕・短辺 480 以下の動画を取得
│  transcript.py 字幕の読み取り（json3 / vtt）→ 無ければ音声を mlx-whisper で文字起こし
│  frames.py     imageio-ffmpeg でコマ抜き（一定間隔 or 場面転換）→ Pillow で時刻入りの一覧画像
│  cache.py      動画 ID（ローカルは sha256）ごとのキャッシュと期限切れの削除
└──────────────────────────────────────────────────────────────────────┘
                  │
                  ▼
   ~/.cache/video-understanding/<key>/
       info.json  video.mp4  audio.wav  caption-<lang>.json  captions.<kind>.<lang>.json3
       transcript.json  frames/<t>.jpg  sheets/<spec>.jpg
```

- MCP は CLI と同じ関数を呼ぶだけの薄い窓口にする。処理の本体はテストしやすい純粋な Python 関数に寄せる。
- `claude mcp add --scope user` で登録し、モノレポ以外のディレクトリで開いた Claude Code からも使えるようにする。

### 4.2 データモデル

DB は持たない。キャッシュディレクトリだけで管理する。

| ファイル | 内容 | 消すタイミング |
|---|---|---|
| `info.json` | 動画の情報（タイトル・投稿者・長さ・説明・チャプター・取得日時・取得元 URL） | 消さない（小さい） |
| `video.mp4` | 短辺 480 以下の動画本体 | 最終利用から 14 日（`VIDEO_UNDERSTANDING_VIDEO_TTL_DAYS`） |
| `captions.*.json3` | YouTube の字幕（手動 > 自動の順で 1 本） | 消さない |
| `caption-<lang>.json` | 指定の言語で選んだ字幕と、自動翻訳かどうか（無ければ「無し」と記録。取得に失敗したときは書かず、次に取り直す） | 消さない |
| `transcript.json` | 正規化した時刻つきテキスト（`source`: `captions_manual` / `captions_auto` / `whisper:<model>`） | 消さない |
| `frames/`・`sheets/` | 抜き出したコマ・一覧画像 | 動画本体と同じ |

キャッシュのキー: YouTube は動画 ID、ローカルファイルは中身の sha256（パスが変わっても同じ動画と分かる）。

### 4.3 API

#### MCP ツール

| ツール | 引数 | 返すもの |
|---|---|---|
| `video_overview` | `source`（URL かパス）, `interval_sec`（省略時は長さから自動: 40 コマ以内になる、きりのよい間隔。36 秒なら 1 秒、60 秒なら 2 秒）, `lang`（既定 `ja`） | 情報（テキスト）＋字幕か文字起こし（時刻つき、長いときは先頭から上限まで）＋一覧画像（最大 2 枚、1 枚 20 コマまで） |
| `video_frames` | `source`, `start`, `end`, `fps`（既定 10、最大 30）, `crop`（任意: `x,y,w,h` を比率で） | 区間のコマの一覧画像（最大 30 コマ）＋各コマの時刻 |
| `video_transcript` | `source`, `lang`, `force_whisper`（字幕があっても文字起こしする） | 時刻つきテキスト全文と、その出どころ |

- 戻り値の画像は fastmcp の `Image`（MCP の image content）で返し、Claude がファイルを経由せずにそのまま見られるようにする。
- 字幕・説明文などの外部のテキストは、すべて `<untrusted_video_text source="...">…</untrusted_video_text>` で囲んで返す。

#### CLI

```
uv run video-understanding overview <source> [--interval 1] [--lang ja] [--out DIR]
uv run video-understanding frames <source> --start 2.0 --end 3.0 [--fps 10] [--crop 0.2,0,0.6,1]
uv run video-understanding transcript <source> [--force-whisper]
uv run video-understanding gc            # 期限切れの動画本体・コマを消す
```

CLI は一覧画像をファイルに書き出し、そのパスを表示する（Claude Code が Read で見られる）。

### 4.4 主要モジュール

```
video-understanding/
├ pyproject.toml        依存: yt-dlp, imageio-ffmpeg, pillow, fastmcp, mlx-whisper（extra: whisper）
├ README.md             使い方・MCP の登録手順・利用上の注意
├ video_understanding/
│ ├ source.py           Source（kind: youtube | local, key, url/path）。許可判定はここだけ
│ ├ fetch.py            yt-dlp の呼び出し（format: "bv*[height<=854][width<=854]+ba/b[height<=854][width<=854]"、字幕は json3）
│ ├ api.py              CLI と MCP が呼ぶ処理（prepare / overview / frames と表示）
│ ├ transcript.py       json3 / vtt の読み取り・重複行の除去・Segment(start, end, text) への正規化、whisper の呼び出し
│ ├ frames.py           extract(times) / sample(interval) / scenes(threshold) と contact_sheet(frames, cols, max_px)
│ ├ cache.py            キャッシュのパス・最終利用時刻・gc
│ ├ config.py           環境変数（許可ディレクトリ・TTL・上限値・whisper のモデル）
│ ├ cli.py
│ └ server.py           fastmcp のツール定義（cli と同じ関数を呼ぶ。エントリポイント video-understanding-mcp）
└ tests/
```

- 音声は imageio-ffmpeg で 16kHz モノラルの float32 に変換し、numpy の配列のまま `mlx_whisper.transcribe` に渡す（mlx-whisper が PATH 上の `ffmpeg` を探さずに済む）。
- mlx-whisper は optional extra（`uv sync --extra whisper`）にする。入っていないときに字幕の無い動画を渡すと、
  「字幕がなく、文字起こしの機能が入っていない」と分かる文で返す。

### [必須] 4.5 Test Plan

- **Unit**（ネットワークなし・既定で実行）
  - `source`: 許可する URL の形（watch / shorts / youtu.be / 余分なクエリ付き）と拒否する URL（他ドメイン、プレイリスト）。
    ローカルパスの許可判定（許可外・`..`・許可外を指すシンボリックリンクを拒否）
  - `transcript`: json3 / vtt の読み取り、自動字幕の重複行の除去、時刻の正規化。字幕の選び方（手動 > 自動 > whisper）
  - `frames`: 時刻の並べ方・間隔の自動決定・一覧画像の大きさ（長辺 1568px 以下、1 枚 20 コマ以下）
  - `cache`: キーの決め方、TTL を過ぎたものだけ `gc` で消えること
  - 戻り値で、外部テキストが `<untrusted_video_text>` に囲まれていること
- **Integration**（ネットワークなし・既定で実行）
  - imageio-ffmpeg の `testsrc` で数秒の動画をテスト中に作り、`frames` → 一覧画像 → MCP ツール（fastmcp の in-memory Client）まで通す。
    返る画像の枚数・時刻の表示を確かめる
  - yt-dlp はモックし、字幕あり / 自動字幕のみ / 字幕なし（whisper へ）の分岐を確かめる
- **Network**（`pytest -m network`、手動で実行）
  - 公開されている短い YouTube ショート 1 本で overview → frames → transcript が通る
- **Manual / E2E**
  - [ ] `claude mcp add --scope user` で登録し、別のディレクトリで開いた Claude Code から `video_overview` が呼べる
  - [ ] 2026-11-23 の比嘉兄弟のショートで、人の補足なしに「左足に乗ってから回す」という内容が読み取れる
  - [ ] `golf_data/<shot>/Side.mp4`（許可ディレクトリに追加して）の切り返し区間を `video_frames` で取り出せる
  - [ ] 2 回目の呼び出しがキャッシュから数秒で返る

### [推奨] 4.6 Migration / Rollback

- **Migration**: なし（新規のディレクトリとユーザーの MCP 設定の追加だけ）
- **Rollback**: `claude mcp remove --scope user video-understanding` とキャッシュディレクトリの削除で元に戻る
- **既存ユーザー影響**: なし

### [推奨] 4.7 Feature Enablement

| 環境変数 | 既定 | 意味 |
|---|---|---|
| `VIDEO_UNDERSTANDING_CACHE_DIR` | `~/.cache/video-understanding` | キャッシュの場所 |
| `VIDEO_UNDERSTANDING_ALLOWED_DIRS` | （空 = ローカルファイルは不可） | ローカル動画を読めるディレクトリ（`:` 区切り） |
| `VIDEO_UNDERSTANDING_VIDEO_TTL_DAYS` | `14` | 動画本体・コマを残す日数 |
| `VIDEO_UNDERSTANDING_MAX_DURATION_SEC` | `1800` | 全体処理を受け付ける長さの上限 |
| `VIDEO_UNDERSTANDING_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | 文字起こしのモデル |
| `VIDEO_UNDERSTANDING_WHISPER_PROMPT` | ゴルフ用語の一覧 | 文字起こしの用語ヒント |

---

## [推奨] 5. Operational Concerns

### 5.1 Monitoring

- 常駐しないので監視はしない。MCP サーバのログ（stderr）に、取得元・キャッシュの当たり外れ・処理時間を 1 行ずつ出す。
- `video-understanding gc` は手動で実行する（必要なら後で launchd に載せる）。

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| YouTube の取得が急に失敗する | YouTube 側の変更。`uv lock --upgrade-package yt-dlp && uv sync` |
| 字幕が「取得できない」になる | 字幕が無い動画。`--extra whisper` を入れていれば自動で文字起こしに切り替わる |
| 初回の文字起こしが遅い | モデルの取得中（約 1.6GB）。2 回目からは数十秒以内（60 秒の動画で目安 10 秒） |
| ローカル動画が「許可されていない」 | `VIDEO_UNDERSTANDING_ALLOWED_DIRS` にそのディレクトリを追加して MCP を登録し直す |

### 5.3 Dependencies

- yt-dlp（YouTube からの取得）
- imageio-ffmpeg（ffmpeg の実行ファイル）・Pillow（一覧画像）
- fastmcp（MCP サーバ。kanie-lab-agent の google-search-mcp と同じ）
- mlx-whisper（optional。Apple Silicon の Mac が前提）
- Hugging Face（whisper のモデルの初回取得のみ）

### [推奨] 5.4 Non-Functional Requirements

#### 性能
- 60 秒のショート: 初回の `video_overview` は 30 秒以内（文字起こしがある場合は 60 秒以内）、2 回目は 5 秒以内

#### コスト
- 外部の課金はなし。Claude 側の読み取り量は、`video_overview` 1 回で画像 2 枚＋字幕程度に抑える

#### プライバシー / データ保持
- 送り先は YouTube（取得）と Hugging Face（モデルの取得）だけ。ローカル動画は外に出ない
- 動画本体は 14 日で消す。情報・字幕は残す

---

## [推奨] 6. Drawbacks

- yt-dlp に頼る以上、YouTube 側の変更で止まる可能性は無くせない。
- 利用規約上グレーな取得を伴うため、用途を「自分で見て理解する」ことに絞り続ける運用上の規律が要る。

## [必須] 7. Alternatives

### 案 A: Gemini API に YouTube の URL を渡して内容を聞く
- 概要: Gemini は公開動画の URL を直接読めるため、ダウンロード無しで要約や質問への回答が得られる。
- 却下理由（主経路としては）: 返ってくるのは Gemini の解釈で、Claude がコマ単位で確かめられない。
  自分のスイングとの数値の比較に向かない。課金が発生し、モノレポの方針として LLM 呼び出しは llm-gateway（PROPOSAL-0014）を通す必要がある。
  「ざっくり内容だけ知りたい」ときの補助ツール（`video_ask_gemini`、gateway 経由）として、後で足すことは検討する。

### 案 B: MCP を作らず、CLI ＋ Claude Code のスキルだけにする
- 概要: CLI が一覧画像をファイルに書き、Claude Code が Bash と Read で使う。
- 却下理由: Claude Code だけなら成り立つが、Claude Desktop からは使えない。画像をファイル経由で受け渡すため手順も増える。
  本提案でも CLI を本体にしているので、MCP は薄い窓口の追加だけで済む。

### 案 C: 既存の YouTube 向け MCP サーバ（OSS）を使う
- 概要: 字幕の取得だけを行う MCP サーバは複数公開されている。
- 却下理由: 字幕しか取れず、今回足りなかった「動き」（コマ画像）が見られない。ローカルの動画にも使えない。
  第三者の MCP サーバをホストで動かすことになり、中身の確認と更新の追従も必要になる。

### 案 D: golf-notes-agent の中に作る
- 概要: Phase 4 のスイング解析の一部として作る。
- 却下理由: golf-notes-agent は Docker の中で動き（GPU が使えない）、LINE 経由の利用が主。
  参考動画を Claude Code で見るという今回の用途は、ゴルフに限らずホストで使いたい。
  共通の部品としてモノレポ直下に置き、golf-notes-agent からはライブラリとして使う。

---

## [必須] 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-11-23 | Draft | 初稿 |
| 2026-11-24 | Implementing | 設計を PR #287 でマージ。PR1 の確認結果を反映（imageio-ffmpeg の arm64 版・ffprobe 無し、縦長動画の画質、YouTube の JS 実行環境と字幕の 429、自動字幕の翻訳の扱い、自動の間隔） |
| 2026-11-25 | Implementing | PR1 (#288) をマージ。PR2: MCP サーバ。server.py はパッケージの中に置き、`video-understanding-mcp` で起動する。字幕の 429 は日をまたいでも続いたため、内容を確実に取るのは PR3 の文字起こしが前提になる |

### 実装フェーズ

| PR | 内容 | 完了条件 |
|---|---|---|
| PR1 | パッケージの骨組み・`source` / `fetch` / `frames` / `cache`・CLI の `overview`（字幕あり動画）と `frames` | CLI で YouTube ショートの一覧画像と字幕が取れる |
| PR2 | MCP サーバ（3 ツール）・外部テキストの囲み・README と登録手順 | 別ディレクトリの Claude Code から呼べる |
| PR3 | mlx-whisper での文字起こし（optional extra）・用語ヒント・`gc` | 字幕の無い動画でも内容が分かる |
