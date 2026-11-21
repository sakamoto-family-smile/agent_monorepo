# PROPOSAL-0015: security-platform に重大インシデント・ニュースの通知を足す (LINE 日次 + GitHub Issue 週次)

| | |
|---|---|
| **Status** | Draft |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-11-22 |
| **Updated** | 2026-11-22 |
| **Target** | security-platform |
| **Related PRs** | (本 PR: 設計) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

security-platform の LINE の日次まとめは、今は「自分たちが使っているパッケージの脆弱性」と
「記事に出てくる、使っているパッケージと同じ名前の注意喚起」だけを伝えている。
自分たちのパッケージと直接は関係しない **世の中の重大なインシデント・ニュース**
(広く使われる製品のゼロデイ、大規模なサプライチェーン攻撃、主要サービスの情報漏えい、
CISA KEV への新規追加など) は、記事も KEV も取り込んでいるのに通知されない。

これを 2 つの形で届ける。

1. **毎日の LINE**: 日次まとめの直後に「重大ニュース」を 1 通。KEV の新規追加と、
   LLM が重大と判定した記事の上位 5 件を、日本語の要約 1〜2 行と元記事の URL で並べる
2. **週 1 回の GitHub Issue**: private リポジトリに「週次セキュリティニュース」を 1 件立てる。
   その週の重大・高の記事と KEV の追加を一覧にし、月曜の LINE に Issue のリンクを載せる

範囲は「重大なものは全部」。そのうち使っている技術 (Python / npm / GCP / GitHub /
Claude・MCP / Docker / macOS など) に関係するものを上に並べる。

## 2. Motivation

- 今の通知は「自分たちに直撃するもの」に絞った設計で、それ自体は正しい。ただ、
  直撃しなくても知っておくべき出来事 (使っている SaaS の侵害、同じ種類の攻撃の流行、
  開発 PC の OS・ブラウザのゼロデイなど) を拾う手段が、自分でニュースを見に行くことしかない
- 材料はすでにある。14 フィード・約 1,090 件の記事が `intel.db` の `reports` にあり、
  KEV (1,790 件) と EPSS も 1 時間ごとに取得している。足りないのは「重大さの判定」と
  「日本語の短い要約」と「届け方」だけ
- 記事を読む LLM (`extractor` サービス, Max プラン) も、信頼できない入力として扱う仕組み
  (DB に触らせない・ファイルで受け渡す・出力の形を検証する) と一緒にすでに動いている

### 2.1 Goals

- [ ] 毎朝、日次まとめの直後に「重大ニュース」が LINE に届く (KEV の新規追加 + 重大な記事 最大 5 件)
- [ ] 記事 1 件につき、日本語の要約 (140 字以内)・重大度・関係する技術を LLM が付ける。
      LLM の呼び出しは今の抽出と同じ 1 回に相乗りし、記事 1 件あたりの回数を増やさない
- [ ] 毎週月曜に、private リポジトリへ週次まとめの Issue が 1 件立ち、LINE にリンクが届く
- [ ] 使っている技術に関係するものが、日次・週次の両方で上に並ぶ
- [ ] 報道系のフィード (news) を追加し、インシデントの報道も拾う。ただし報道からの
      「危ないパッケージ」の主張は照合に使わない (今の L4 の方針を変えない)

### 2.2 Non-Goals

- 速報の即時通知 (記事が出た瞬間の LINE)。即時性が要るものは、今の P1 通知と早期警告が担う
- 記事全文の翻訳。要約は 1〜2 行だけで、詳しくは元記事を読む
- LLM による週次の総括文 (「今週の傾向」などの作文)。まずは日次の判定を並べるだけにして、
  判定の質を見てから検討する
- ダッシュボードの画面追加、Slack / メールへの配信
- Google Docs など新しい外部サービスへの書き出し (認証情報を増やさない)

---

## 3. Proposal

### 3.1 User Stories

- 朝 9 時、日次まとめのあとに「重大ニュース 3 件」が届く。1 件目は「GitHub Actions の
  人気 Action が侵害され、CI のシークレットが流出 (関係あり: GitHub Actions)」。
  要約を読んで、自分のリポジトリでその Action を使っていないかを確かめる
- 月曜の朝、LINE の「週次まとめ」のリンクから Issue を開き、先週の重大・高の記事と
  KEV の追加を一覧で眺める。気になるものは Issue のコメントにメモを残す

### 3.2 方針

- **LLM の呼び出しは増やさない**: 今の抽出 (L4) の出力に `brief` (重大度・要約・関係する技術) を
  足す。抽出の対象になった記事は、1 回の呼び出しで「危ないパッケージの主張」と「要約」の両方が出る
- **重大度の判定は LLM、並べ方は決まった規則**: LLM には重大度と技術の分類だけを選ばせ、
  何件・どの順で載せるかはコードで決める (同じ入力なら同じ通知になる)
- **KEV は LLM を通さない**: KEV は構造化された一次情報なので、追加日・製品名・説明をそのまま載せる
- **URL は LLM の出力から取らない**: 載せる URL はフィードに書かれている元記事の URL だけ
- **既存のサービス分担を崩さない**: 判定は intel と extractor、文の組み立てと送信は notify。
  notify は intel.db を読み取り専用で開く (今と同じ)

### 3.3 Notes / Constraints / Caveats

- **届くまでの遅れ**: extractor は Max プランの枠を対話の利用と分けるため、夜 (3〜6 時) だけ動く。
  6 時以降に出た記事は翌朝ではなく翌々朝に載ることがあり、最大で約 27 時間遅れる。
  日次のまとめとしては許容し、遅れが気になるようなら昼の処理枠を足す (§4.7)
- **LLM の枠**: 今の上限は 1 日 50 回で、実際の使用は 1 日 10〜15 回程度。報道系のフィードを足すと
  1 日 30 件前後増える見込み。上限を 80 回に上げ、取り出す順を official → research → news にする。
  news は 1 日 30 件までにする。上限に届いた日は news から先に翌日へ回す
- **抽出済みの記事**: 今のプロンプトで抽出済みの記事 (約 140 件) は、要約を作るためだけに
  やり直さない。新しいプロンプトの版からの記事が対象 (週次の初回は件数が少ない)
- **LINE の長さ**: 1 通 4,900 字の上限 (`LINE_TEXT_LIMIT`) に収まるよう、5 件 × 約 250 字 + KEV で
  2,000 字程度に抑える

### 3.4 Risks and Mitigations

| リスク | 影響 | 対策 |
|---|---|---|
| 記事に仕込まれた指示 (プロンプトインジェクション) で、要約に誤誘導の文や URL が入る | LINE に不正なリンクや誤情報が載る | 要約は 140 字・1 行に切り、`http`・`www.` を含むものは捨てる。URL はフィードの値だけ。要約には「(要約)」と付け、判断は元記事で行う前提にする |
| 記事が自分を「重大」と言い張り、重大度が水増しされる | 通知が騒がしくなる | 1 日 5 件の上限。同じ出来事の重複はまとめる。official / research を先に並べる。週次で判定の偏りを見直す |
| LLM の判定がぶれ、重要なものが落ちる | 見逃し | KEV は LLM を通さず全件載せる。直撃するものは今の P1・早期警告で別に届く。重大度の基準をプロンプトに例つきで書き、評価用の記事セットで確かめる (§4.5) |
| 報道系フィードの誤報 | 誤った不安 | news からの主張は照合・早期警告に使わない。要約に出典 (フィード名) を必ず付ける |
| Max プランの枠を使い切り、抽出 (L4) が遅れる | 早期警告が遅れる | news は 1 日 30 件まで・後回し。今の使用量の監視 (`usage.json`) をそのまま使う |
| 週次 Issue の作成に失敗 | 週次が届かない | 次の同期でやり直す。失敗は notify の監視に出す (今の Issues 同期と同じ) |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```text
 フィード (14 + news 3〜4)          CISA KEV
        │ 1 時間ごと                    │ 1 時間ごと
        ▼                               ▼
 intel ── reports ──► data/llm/in/ ──► extractor (夜 3〜6 時, Max プラン)
   ▲                                     │ 1 回の呼び出しで
   │                                     │  claims (今まで) + brief (新規)
   └──── data/llm/out/ ◄─────────────────┘
   │  検証して取り込む
   ▼
 intel.db: report_extractions (+ severity / summary_ja / topics)
           kev_entries (今まで)
   │ 読み取り専用
   ▼
 notify ─┬─ 毎日 9 時: 日次まとめ (今まで) → 重大ニュース (新規)  ──► LINE
         └─ 毎週月曜:  週次 Issue を作成 (新規) ──► GitHub Issues (private)
                       LINE にリンク
```

### 4.2 LLM の出力に足すもの (`src/llm/schema.py`)

`OUTPUT_SCHEMA` に `brief` を足し、`PROMPT_VERSION` を上げる。

```json
{
  "about_specific_packages": true,
  "claims": [...],
  "brief": {
    "severity": "critical",
    "summary_ja": "人気の GitHub Action が侵害され、利用するワークフローの CI シークレットが外部へ送られた。",
    "topics": ["github-actions", "supply-chain"],
    "identifiers": ["CVE-2026-12345"]
  }
}
```

- `severity`: `critical` / `high` / `medium` / `low` / `none` のどれか。プロンプトに基準と例を書く
  - critical: 悪用が確認された、広く使われる製品・サービスの脆弱性やゼロデイ。大規模なサプライチェーン攻撃。
    主要なクラウド・SaaS の侵害で利用者に対応が要るもの
  - high: 広く使われる製品の深刻な脆弱性 (悪用は未確認)。特定の業界・地域に限られた大きな侵害
  - medium 以下: 個別の脆弱性の告知、調査レポート、製品の発表、一般的な助言
- `summary_ja`: 日本語 140 字以内・1 文〜2 文・改行なし。記事に書かれていないことは書かない
- `topics`: 固定の一覧 (`TOPICS`) から最大 5 個。例: `python` `npm` `go` `docker` `github` `github-actions`
  `gcp` `aws` `azure` `anthropic` `mcp` `ai` `macos` `windows` `linux` `browser` `line` `vpn` `supply-chain`
  `ransomware` `data-breach` `other`
- `identifiers`: 記事に書かれた CVE / GHSA の ID (同じ出来事の重複をまとめるのに使う)

`validate_output` で形を検証し、加えて取り込み時に次を確かめる。満たさない `brief` は捨てる
(記事の `claims` の取り込みは続ける)。

- `summary_ja` が 140 字以内で、改行・`http`・`www.` を含まない
- `topics` がすべて `TOPICS` にある
- `identifiers` がすべて CVE / GHSA の形

### 4.3 データモデル

**intel.db** (migration `0009_report_briefs`)。`report_extractions` に列を足す (追加だけで、既存の行は NULL)。

| 列 | 型 | 内容 |
|---|---|---|
| `severity` | TEXT NULL | critical / high / medium / low / none |
| `summary_ja` | TEXT NULL | 検証済みの要約 |
| `topics_json` | TEXT NULL | topics の配列 |
| `brief_identifiers_json` | TEXT NULL | identifiers の配列 |

`feeds` の設定 (`config/feeds.yaml`) に `brief_only: true` を足せるようにする。
`brief_only` のフィード (報道系) の記事は `claims` を捨て、`report_claims` に入れない
(照合・早期警告に使わない)。

**notify.db** (migration `0002_news`)。

| テーブル | 主な列 | 用途 |
|---|---|---|
| `notifications` (既存) | `dedupe_key` = `news:YYYY-MM-DD` / `news-weekly:YYYY-Www` | 二重送信を防ぐ (今と同じ仕組み) |
| `news_issues` (新規) | `week` (PK), `issue_number`, `state`, `body_hash`, `created_at`, `closed_at` | 週次 Issue の記録。翌週の Issue を立てたら前の週を閉じる |

### 4.4 主要モジュール / ファイル

| ファイル | 変更 | 内容 |
|---|---|---|
| `src/llm/schema.py` | 変更 | `brief` の形・`TOPICS`・重大度の基準をプロンプトに追加。`PROMPT_VERSION` を上げる |
| `src/intel/extraction.py` | 変更 | `brief` の検証と保存。`brief_only` のフィードは claims を捨てる。依頼の順を official → research → news、news は 1 日 30 件まで |
| `src/intel/sources/feeds.py` | 変更 | `brief_only` の設定を読む |
| `config/feeds.yaml` | 変更 | 報道系フィードを追加 (候補: BleepingComputer, The Hacker News, Security NEXT, piyolog。RSS が使えるかは実装時に確認) |
| `src/llm/config.py` | 変更 | `daily_limit` の既定を 80 に |
| `src/notify/news.py` | 新規 | 日次・週次の対象を選ぶ規則と、LINE の文・Issue の本文を組み立てる |
| `src/notify/pipeline.py` | 変更 | `run_digest` のあとに重大ニュースを送る。週次ジョブ `notify_news_weekly` を追加 |
| `src/notify/channels.py` | 変更 | GitHub Issues に「作成して URL を返す」「閉じる」を足す (既存のクライアントを使う) |
| `config/news.yaml` | 新規 | 使っている技術 (`stack` = `TOPICS` の部分集合) と、KEV で関係ありとみなす製品名 |
| `src/config.py` | 変更 | `NEWS_DAILY_ENABLED` / `NEWS_WEEKLY_ENABLED` / `NEWS_DAILY_LIMIT` (既定 5) / `NEWS_WEEKLY_WEEKDAY` (既定 月曜) |

**日次の選び方** (`news.py`)

1. 対象は、前回の重大ニュース送信以降に要約が付いた記事と、前回以降に KEV に追加されたもの
2. 記事は `severity` が critical か high のものだけ。同じ CVE / GHSA を持つ記事は 1 件にまとめる
   (official → research → news の順で代表を選び、「ほか n 件の記事」と添える)
3. 並べ方: critical → high、その中で関係あり (`topics` と `stack` が重なる) → なし、
   その中で official → research → news、最後に新しい順
4. 上位 5 件を載せ、残りは「ほか n 件 (週次まとめに載ります)」とだけ書く
5. KEV はすべて載せる (1 日 0〜6 件程度)。関係ある製品を上に並べ、7 件を超えたら残りは件数だけ
6. 記事も KEV も 0 件なら送らない (日次まとめに「重大ニュース: なし」の 1 行を足す)

**LINE の文の例**

```text
【重大ニュース】2026-11-23
■ 悪用が確認された脆弱性 (CISA KEV に追加) 2 件
・CVE-2026-12345 Google Chromium V8 (関係あり: browser)
・CVE-2026-23456 Fortinet FortiOS
■ 記事 3 件 (重大 1 / 高 2)
・[重大] 人気の GitHub Action が侵害され、利用するワークフローの CI シークレットが外部へ送られた。(要約)
  関係あり: github-actions / StepSecurity ほか 2 件
  https://www.stepsecurity.io/blog/...
・[高] ...
ほか 4 件は週次まとめに載ります
```

**週次の Issue**

- 月曜の日次まとめの時刻に、前の週 (月〜日, JST) の分を 1 件作る。タイトルは
  `週次セキュリティニュース 2026-W48 (11/23〜11/29)`、ラベルは `news`
- 本文 (Markdown): 件数のまとめ → 関係ありの記事 → 重大・高の記事 (重大度順、要約・出典・URL・topics)
  → KEV の追加 (表) → 判定の内訳 (medium 以下の件数、要約が付かなかった記事の件数)
- 作成したら LINE に `週次まとめ: <Issue の URL>` を送り、前の週の Issue を閉じる
- 置き場所は今の Issues 同期と同じ private リポジトリ (`GITHUB_ISSUES_REPO`)。
  公開リポジトリには立てない (今の方針と同じ)

### 4.5 Test Plan

- **schema / 取り込み**: `brief` の検証 (長さ・改行・URL 混入・知らない topic・ID の形)。
  不正な `brief` だけ捨てて claims は取り込むこと。`brief_only` のフィードで claims が入らないこと
- **依頼の順と上限**: official → research → news の順、news の 1 日 30 件の上限、上限に届いたら news から後回し
- **日次の選び方**: 重複のまとめ、並べ方、5 件の上限、0 件なら送らないこと、4,900 字に収まること。
  文の組み立てはスナップショットで固定する
- **週次**: 週の境界 (JST の月曜 0 時)、二重作成しないこと、前の週を閉じること、作成に失敗したら次の回にやり直すこと
- **重大度の質**: 既存の記事から 30 件ほどを手で重大度を付けた評価用セットにし、`src/llm/eval.py`
  の仕組みで新しいプロンプトの判定と比べる (critical を落とさないことを重視)。CI では動かさず、プロンプトを変えたときに手で回す
- **既存の通知に影響がないこと**: 今の日次まとめ・P1・早期警告のテストがそのまま通ること

### 4.6 Migration / Rollback

- migration はどちらも列・テーブルの追加だけ。戻すときは `NEWS_*_ENABLED=false` にすれば送らなくなり、
  DB はそのままでよい
- `PROMPT_VERSION` を戻すと、以降の記事に `brief` が付かなくなるだけで抽出 (L4) は今まで通り動く
- 報道系フィードは `config/feeds.yaml` から消せば監視も止まる (今の仕組み)

### 4.7 Feature Enablement

| 設定 | 既定 | 意味 |
|---|---|---|
| `NEWS_DAILY_ENABLED` | false → 動作確認後に true | 日次の重大ニュースを送る |
| `NEWS_WEEKLY_ENABLED` | false → 1 週分たまってから true | 週次の Issue を作る |
| `NEWS_DAILY_LIMIT` | 5 | 日次に載せる記事の数 |
| `LLM_DAILY_LIMIT` | 80 | LLM の 1 日の呼び出し上限 (今は 50) |
| `LLM_NEWS_DAILY_LIMIT` | 30 | そのうち報道系に使ってよい回数 |
| (将来) 昼の処理枠 | なし | 遅れが気になるときに extractor の処理時間帯を 1 つ足す |

---

## 5. Operational Concerns

### 5.1 Monitoring

- 追加したフィードは、今の `feed:<id>` の監視 (取得が止まったら LINE) にそのまま乗る
- extractor の使用量・停止理由は今の `usage.json` の監視を使う
- 新しい監視 `news:brief`: 記事は届いているのに、48 時間 `brief` が 1 件も付かなければ LINE で知らせる
  (プロンプトの変更や LLM の出力の形の崩れで、要約だけ全部捨てられている状態を見つける)
- 週次 Issue の作成の失敗は、今の Issues 同期と同じく notify のジョブの失敗として記録・監視する
- Healthchecks.io の ping は今の notify のものを使う (新しい項目は足さない)

### 5.2 Troubleshooting

| 症状 | 確認すること |
|---|---|
| 重大ニュースが届かない | `NEWS_DAILY_ENABLED`、notify のログ、`notifications` の `news:<日付>` が `skipped` でないか、その日の対象が 0 件でないか |
| 要約が付かない | `report_extractions` の `prompt_version` と `severity`、extractor のログ (出力の形の検証で捨てていないか) |
| 報道系の記事ばかり並ぶ | 並べ方は official → research → news。news の critical が多いならプロンプトの基準を見直す |
| 週次 Issue が立たない | `GITHUB_ISSUES_*` の設定、`news_issues` の記録、notify のジョブの失敗 |

### 5.3 Dependencies

- 既存: LINE Messaging API (セキュリティ通知用 Bot)、GitHub Issues (private リポジトリ, fine-grained PAT)、
  Claude Code (Max プラン, extractor)、CISA KEV
- 新規: 報道系フィード 3〜4 件 (RSS)。新しい認証情報は増やさない

### 5.4 Non-Functional Requirements

- LLM の呼び出しは記事 1 件につき 1 回のまま。1 日の上限は 80 回
- 日次の LINE は 1 通・2,000 字程度。週次は Issue 1 件 + LINE 1 通
- 外部と通信するのは今と同じ notify (送信) と intel (取得) だけ。extractor はネットワークの外へ記事を出さない
  (Claude への送信を除く)

---

## 6. Drawbacks

- LLM の出力の形を広げるので、抽出 (L4) のプロンプトと要約のプロンプトが 1 つに混ざる。
  片方だけ直したいときも `PROMPT_VERSION` が上がり、評価をし直す必要がある
- 夜だけの処理なので、ニュースとしては最大 1 日強遅れる
- 重大度は LLM の判定なので、ある程度のぶれは避けられない

## 7. Alternatives

### 案 A: 要約用に LLM を別に呼ぶ

抽出と要約のプロンプトを分けられ、評価もしやすい。ただし LLM の呼び出しが記事 1 件につき 2 回になり、
Max プランの枠 (対話と共有) を倍使う。まずは相乗りにし、混ざって困るようなら分ける。

### 案 B: キーワードの規則だけで重大度を決める

LLM を使わずに済むが、「ゼロデイ」「侵害」などの語は一般的な解説記事にも出るため、判定の質が低い。
要約も作れない。KEV のように構造化された情報にだけ使う (本提案でもそうしている)。

### 案 C: 週次のドキュメントを Google Docs などに書き出す

読みやすい文書にできるが、notify に新しい OAuth の認証情報を持たせることになる。
GitHub Issues はすでに使っていて、スマホからも読め、コメントでメモも残せる。

### 案 D: LINE をやめて週次のドキュメントだけにする

通知は静かになるが、重大なものに気づくのが最大 1 週間遅れる。

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-11-22 | Draft | 初稿 |

予定している PR:

1. intel / extractor: `brief` の出力・検証・保存、報道系フィード (`brief_only`)、依頼の順と上限
2. notify: 日次の重大ニュース (選び方・文の組み立て・監視 `news:brief`)
3. notify: 週次の GitHub Issue と月曜の LINE のリンク
