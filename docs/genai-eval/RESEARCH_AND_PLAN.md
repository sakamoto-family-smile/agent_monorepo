# 生成AIアプリケーション評価レビューの仕組み — 調査と構築方針

> Status: Draft（調査・方針整理）
> 対象: T2T（Text-to-Text）生成AIアプリケーションの「ドキュメント / コード」を品質観点でレビューする仕組み
> 出典書籍: 『生成AIアプリケーション評価入門』松木晋祐 著, 技術評論社, 2026, ISBN 978-4-297-15614-5

本ドキュメントは、上記書籍の評価観点・品質基盤モデルを調査し、それを **Claude Code のスキル / エージェント**
として実装し、**GitHub Actions で自動レビュー**する仕組みを作るための方針をまとめる。

---

## 1. 書籍の内容調査（要約）

### 1.1 全体構成（目次）

| 章 | テーマ | 主な内容 |
|---|---|---|
| 1 | 評価の概要 | 生成AIアプリの特徴 / 基本構造モデル / 評価プロセスモデル / 開発ライフサイクルでの評価アプローチ |
| 2 | **評価基盤モデルと評価アプローチ** | 品質モデル / ML利用システムの外部品質特性レベル / 品質モデル×テストタイプ / **評価観点基盤モデル** / 製品独自の評価観点モデル+メトリクス設計 / 開発・QA の役割分担 |
| 3 | 基本的な評価メトリクス | 混同行列ベース / 検索・RAG向け / 生成テキスト内容一致 |
| 4 | ツールによる評価 | **LLM-as-a-Judge** / 評価環境構築 / 評価実行 / **pytest 統合** |
| 5 | セキュリティ評価 | **OWASP LLM Top 10 (2025)** / レッドチーミング |
| 6 | AIエージェントの評価 | エージェントのパターン/構造別の評価観点 / エージェント評価メトリクス |
| 7 | その他のトピック | — |

### 1.2 品質基盤モデルの土台（著者の一次情報から特定）

本書の「品質モデル / 外部品質特性」は、著者（snsk 氏）が公開している解説と整合する以下の標準・ガイドラインの系譜にある:

- **ISO/IEC 25059:2023**（AIシステムの製品品質モデル。ISO/IEC 25010 の AI 拡張）
  - AI 固有特性: Functional adaptability / Robustness / Transparency / Intervenability / User controllability 等
  - 重要前提: ML モデルを使う AI システムは「全状況での functional correctness を保証できない」
- **QA4AI ガイドライン**（5軸: Data Integrity / Model Robustness / System Quality / Process Agility / Customer Expectation）
- **産総研 機械学習品質マネジメントガイドライン**

> ⚠️ **本書オリジナルの「評価観点基盤モデル（2.4/2.5）」の具体的な階層・命名・図は、二次情報では再現できない。**
> 現物の第2章の該当部を取り込んで `references/quality-model.md` に正確に書き起こす（下記 TODO）。

### 1.3 評価メトリクス（第3〜4章, 特定済み）

| カテゴリ | メトリクス例 |
|---|---|
| 混同行列ベース | Accuracy / Precision / Recall / F1 |
| 検索・RAG向け | Context Precision / Context Recall / Faithfulness / Answer Relevancy（RAGAS 型） |
| 生成テキスト内容一致 | BLEU / ROUGE / BERTScore |
| LLM ベース | **LLM-as-a-Judge**（ルーブリック採点） |
| セキュリティ | OWASP LLM Top 10 (2025) 観点 / レッドチーミング |

---

## 2. 既存リポジトリ資産との接続

このモノレポには評価/品質の関連資産が既にある。重複を避けて再利用する。

| 資産 | 場所 | 関係 |
|---|---|---|
| `eval-harness` スキル | `.claude/skills/ecc/eval-harness/` | EDD / pass@k。メトリクス実行の素地 |
| `ai-regression-testing` スキル | `.claude/skills/ecc/ai-regression-testing/` | AI が書いたコードの盲点を突くテスト |
| `security-review` スキル | `.claude/skills/ecc/security-review/` | セキュリティ観点（OWASP LLM と接続） |
| security-platform | `security-platform/` | MCP Proxy / レッドチーミング (`.promptfoo/redteam.yaml`) |
| driving-license `quality_reviewer` | `driving-license-bot/app/agent/quality_reviewer.py` | 実アプリでの LLM-as-a-Judge 実装例 |
| CI | `.github/workflows/{pr-tests,pr-security}.yml` | 追加する eval-review workflow の参考 |

---

## 3. 構築方針

### 3.1 成果物の全体像

```
評価観点の定義（本書ベース）
  └─ references/quality-model.md        ← 本書第2章の評価観点基盤モデルを書き起こし（要・現物）
       │
       ├─ Skill:  genai-eval-review     ← 評価観点チェックリスト + レビュー手順（知識）
       │            .claude/skills/ecc/genai-eval-review/SKILL.md
       │
       ├─ Agent:  genai-eval-reviewer   ← 観点を適用して diff/docs をレビューする実行体
       │            .claude/agents/genai-eval-reviewer.md
       │
       └─ CI:     .github/workflows/genai-eval-review.yml
                    PR の docs/コード差分にエージェントを当てて観点レビューコメント
```

- **Skill** = 「何を見るか」（評価観点・品質特性・メトリクスの知識ベース、チェックリスト）。
- **Agent** = 「どう見るか」（diff/設計書を読み、観点で採点し、指摘を構造化出力する手順）。
- **CI** = 「いつ回すか」（PR トリガで自動実行し、レビューコメント or サマリを残す）。

### 3.2 評価観点モデル（T2T 向け・ドラフト構造）

本書第2章を取り込むまでの**仮の器**。現物が来たら命名・階層を差し替える。
T2T アプリの「ドキュメント/コード」レビューに使えるよう、観点を以下の層で持つ。

| レイヤー | 観点（仮） | ドキュメントで見る | コードで見る |
|---|---|---|---|
| 機能適合性 | 正確性 / 関連性 / 一貫性 | 要件・受入基準が観点化されているか | 出力検証・スキーマ検証の有無 |
| RAG/検索品質 | Faithfulness / Context Precision・Recall | 根拠提示の設計があるか | 検索→生成の評価メトリクス実装 |
| 堅牢性 | プロンプトインジェクション耐性 / 異常入力 | 脅威と対策が設計されているか | 入力検証・サニタイズ・ガードレール |
| セキュリティ | OWASP LLM Top10 (2025) | リスク登録と緩和策 | 秘密情報の扱い・出力の無害化 |
| 透明性/説明性 | 根拠提示 / ログ・トレース | 監査可能性の設計 | observability 計装 |
| 評価運用 | メトリクス定義 / 回帰評価 | 評価計画・合否基準 | eval の自動テスト（pytest 統合） |

> 各観点に **severity（CRITICAL/HIGH/MEDIUM/LOW）** と **判定根拠（本書/標準の出典）** を紐付ける。

### 3.3 レビュー対象（両方をスコープ）

1. **ドキュメント / 設計書**: 評価観点が設計に織り込まれているかの「観点レビュー」。LLM 不要でも回る軽量版から。
2. **コード**: 生成AIアプリ実装に評価・ガードレール・検証が入っているかのレビュー。

### 3.4 GitHub Actions の流れ（案）

```
PR (docs/** または 対象コード変更)
  → changed files 抽出
  → genai-eval-reviewer エージェント実行（観点モデルを適用）
  → 出力: 観点別の指摘 + severity + 出典
  → PR にレビューコメント / サマリ Job Summary
```

- まずは**非ブロッキング**（информ）で開始し、観点が安定したら CRITICAL のみ fail にする。
- 既存 `pr-security.yml` / `pr-tests.yml` と並列の独立 workflow。

---

## 4. 未確定事項（要相談・要現物）

1. **本書第2章「評価観点基盤モデル」(2.4/2.5) の正確な構造** — 現物の該当部を共有いただき `references/quality-model.md` に書き起こす。本仕組みの観点定義の根拠になる中核。
2. CI でのエージェント実行方式（Claude Code Action / API 直叩き / ローカルメトリクスのみ）。コスト・権限と相談。
3. ブロッキング方針（最初は情報提供のみ → 段階的に CRITICAL を必須化）。

---

## 5. 次のアクション

- [ ] （ユーザー）第2章 2.2 / 2.4 / 2.5 の該当部を共有
- [ ] 共有内容を `references/quality-model.md` に正確に書き起こし
- [ ] `genai-eval-review` スキルの観点チェックリストを確定
- [ ] `genai-eval-reviewer` エージェントを作成
- [ ] `genai-eval-review.yml`（PR 非ブロッキング）を追加し、サンプル PR で試走
