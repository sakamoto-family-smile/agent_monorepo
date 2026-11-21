# チェック処理をループ・エンジニアリングで設計する

本書は、抽出/検証パイプラインの **品質チェックをエージェント主導のループ** にする設計指針。
論文 *Loop Engineering: The Anthropic Playbook for Designing Systems That Prompt Your Agents*
(HuaShu, 2026; Osmani/Steinberger/Cherny) の枠組みを、本リポジトリの「チェック処理」へ写像する。

## 0. 用語の対応 (この設計での「チェック処理」)

「チェック処理」= 抽出/検証パイプラインの品質を継続検査し、劣化を検知して直す
**自己修復チェックループ**（設計ガイド §4.8 ＋ PR 監視）。論文の中核「ループの中に
『No と言える検査(Verification)』を据える」が、そのまま本書の主題に重なる。
1 ターン内の検査の実体は、本リポジトリの **決定的検証層**(`validate/`: 接地/帰属/τ)。

> エージェントは **ループの外** に立ち、ループを設計・駆動する (論文の核心: 自分を
> 「プロンプトする人」から「ループを作る人」へ置き換える)。

## 1. 論文の骨子 (引用元の用語)

- **1 ターン = 5 つの動き**: Discovery → Handoff → **Verification** → Persistence → Scheduling。
  Verification だけが「No」と言える動き。Scheduling が次ターンへ閉じてループになる。
- **6 つのパーツ**: Automations / Worktrees / Skills / Connectors(MCP) / Sub-agents(generator–evaluator) / Memory。
- **中心原理**: 書いた本人に採点させない。独立した懐疑的 **Evaluator**(別エージェント・別モデル)を
  「壊れている前提(assume-broken)」で立て、**読むだけでなく実行して**判定する。
- **誤りのコストは“生き延びたターン数”に比例**。ループは誤りを増幅する装置なので、
  すべては「誤りと発見の距離を縮める」ために存在する。
- **4 つのサイレントコスト**: verification debt / comprehension rot / cognitive surrender / token blowout。

## 2. エージェント主導チェックループの 1 ターン (5 moves)

```text
[Scheduling] 毎時トリガ(Cron) または PR webhook で起床
   │  (対象が無ければ静かに終了 → 次ターンへ)
   ▼
[Discovery] 何を検査すべきか自分で発見
   ・新規push / CI結果 / レビューコメント / メトリクス時系列を読む
   ・「どのカラム・どの指標が・いつから劣化したか」を特定 (診断は skill 化)
   ▼
[Handoff] 検査対象を隔離して各エージェントへ
   ・PR/差分ごとに git worktree を切り、並行で検査・修正案を作成
   ▼
[Verification] ★「No」と言える中核★ — 二層構成
   (a) 決定的チェック (LLM不要):
        - 検証層を再実行 (grounding / 帰属 / 数値再検証 / τ)  → FP=0 か
        - golden dataset で precision@coverage 回帰ゲート (既存値を下回ったら No)
        - lint / pytest / SAST
   (b) 独立 Evaluator (別エージェント・別モデル, assume-broken):
        - 実際に走らせて判定する (“diff を読んで良さそう” で通さない)
        - 修正を書いたエージェントには絶対に採点させない
   │  PASS                                  │  REJECT (理由付き)
   ▼                                        ▼
[Persistence]                            Handoff へ差し戻し / 人間 inbox へ
   ・結果を disk へ: PRコメント, golden datasetへ hard example 追加,
     state.md, メトリクス
   ▼
[Scheduling] 次ターンへ: 未完は state に残し翌起床で再開
   ・merged / closed なら Cron 削除 ＋ 購読解除でループ終了
```

**人間チェックポイント** (固定):
1. Evaluator が REJECT を繰り返す / 判断が曖昧な箇所 → inbox (= `AskUserQuestion`)。
2. **マージ権限は常に人間**。抽出ロジックに触る変更は原則レビュー必須 (precision 最優先のため)。

## 3. 基本コンポーネント(6 parts) → チェック処理での該当処理

| Loop Engineering の部品 | 対応 move | チェック処理での該当 |
|---|---|---|
| **Automations** | Scheduling | 毎時の自己チェックイン (`CronCreate`) ＋ PR webhook 購読 (`subscribe_pr_activity`)。無ければ“1回の検査”でループでない |
| **Worktrees** | Handoff | PR/差分ごとに隔離 worktree を切り、検査・修正を並行 (編集衝突を排除) |
| **Skills** | Discovery | 「どのメトリクスを・どの順に見るか」を恒久知識化した診断 skill (Validator別reject率 / ECE / grounding率 の読み方)。cron に手順を貼らず skill を起動 |
| **Connectors (MCP)** | Persistence / Discovery | GitHub MCP (CI状態 / レビュー / PR操作)、監視 (Langfuse 等)、将来の EDINET。ループの“視野半径”を決める |
| **Sub-agents (生成/評価分離)** | **Verification** | 修正を書くエージェントと独立の懐疑 Evaluator (`code-reviewer` / 別モデル) を分離。＋ 決定的検証層が機械的な“No”を担う |
| **Memory** | Persistence | golden dataset (hard example 蓄積) ＋ `state.md` ＋ PRコメント。context が消えても repo は忘れない＝翌ターン継続の根拠 |

> **チェック処理で最重要の該当物は Verification の部品＝「Sub-agents(独立評価者)＋決定的検証層」**。
> 論文の「say no」を二層で実装する: 機械的に弾く決定的層 (FP=0 回帰ゲート) ＋ 意味を見る独立 Evaluator。

## 4. 設計で効く論文の主張 (と本書への含意)

- **自分で採点させない**: 自己修復で“修正を書いたエージェント”に合否を出させると甘くなる。
  Evaluator は別エージェント・別モデル・assume-broken。決定的検証層がまず門番になり、
  その上に懐疑 Evaluator を乗せる。
- **読むだけでなく実行**: Evaluator は pytest を実行し golden で precision@coverage を実測する。
- **誤りは生き延びたターン数だけ高コスト**: マージ前に回帰ゲート (FP=0 / precision@coverage 非劣化) を
  必須化し、誤りと発見の距離を最短化する。
- **4 つのサイレントコストの番人**:
  - verification debt → 決定的ゲートで自動化し貯めない
  - comprehension rot → 変更 diff に合わせた監視を自動生成、知識は skill に集約
  - cognitive surrender → マージは人間、Evaluator は理由列挙を必須に
  - token blowout → LLM Evaluator(V5) は決定的層で確定しない高リスク箇所だけにカスケード適用 ＋ budget cap

## 5. 既存資産との対応 (現状)

本パイプラインは **抽出 = Generator / 検証層 = Evaluator** という論文の中心原理を既に体現している。
チェックループ化に必要な部品の現状:

| 部品 | 状態 | 実体 |
|---|---|---|
| Automations / Scheduling | ✅ | `CronCreate`(毎時) ＋ `subscribe_pr_activity` |
| Verification | ✅ | 決定的検証層 ＋ `test_*` の `false_positive==0` 回帰ゲート (独立 Evaluator 起動は今後組込み) |
| Memory | ◯ | golden dataset 設計済 (実体蓄積は今後) / `state.md` は未 |
| Connectors | ✅ | GitHub MCP (監視連携は未接続) |
| Worktrees | ✗ | 修正並行時に導入 |
| Skills | ◯ | 診断手順の skill 化は今後 |

## 6. まとめ

チェック処理を「エージェント主導ループ」にする＝ **5 moves で 1 ターンを回し、心臓部 Verification を
“決定的検証層 ＋ 独立 Evaluator(assume-broken・実行して判定)” で構成し、回帰ゲートで誤りの生存
ターン数をゼロに抑える** こと。6 parts のうちチェック処理に最も該当するのは **Sub-agents(生成/評価
分離) と Memory(golden dataset)** で、**Automations** が“1回の検査”を“ループ”に変える。

> 参考: *Loop Engineering* (HuaShu, 2026). 本書は同論文の枠組みを本リポジトリのチェック処理へ
> 写像した設計メモであり、論文本文の再配布ではない。
