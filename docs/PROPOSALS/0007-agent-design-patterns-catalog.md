# PROPOSAL-0007: エージェントデザインパターン カタログとサンプル実装計画 `agent-patterns/`

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-24 |
| **Updated** | 2026-05-24 |
| **Target** | `agent-patterns/` (新規ディレクトリ、cross-agent reference) |
| **Related PRs** | (none yet、本 PR が初版) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

エージェント (Agentic LLM システム) の代表的なデザインパターンを **6 つの軸** に分けて多角的にカタログ化し、その中から学習価値・実用価値の高い **10 パターン** を最小サンプル実装としてモノレポ内 `agent-patterns/` ディレクトリに整備する提案。

既存エージェント (`kanie-lab-agent` / `paper-qa-agent` 等) の設計判断の根拠を後付け文書化する効果と、新規エージェント追加時の **設計選択の早見表** としての効果を狙う。教材としての OSS 公開も視野に入れる。

## 2. Motivation

### 現状の課題

現在モノレポには 6 つの実装エージェントがあるが、それぞれが採用しているパターンが**用語レベルで不揃い**:

| エージェント | 採用パターン (本提案で確定する用語で記述) |
|---|---|
| `kanie-lab-agent` | Supervisor (LLM 駆動) + sub-agent |
| `paper-qa-agent` (提案中) | Supervisor + 内部 Workflow Orchestrator (決定論) |
| `driving-license-bot` | Workflow Orchestrator + Cross-Check (異モデル) |
| `tech-news-agent` | Workflow Orchestrator + Map-Reduce |
| `stock-analysis-agent` | Workflow Orchestrator + Sub-agent (並列) |
| `lifeplanner-agent` | Workflow Orchestrator (LLM はアドバイザーとして末尾配置) |

各エージェントの設計書では「Orchestrator」「Supervisor」「Sub-agent」「Worker」等の用語が **流派違いで混在** しており、新規エージェント追加時に既存パターンを参照しづらい。また、Self-Refine / Chain-of-Verification / HyDE / Debate 等の **未採用パターンの存在を体系的に把握できていない**。

### 放置するとどうなるか

- 新規エージェント設計時に毎回ゼロから設計パターンを調査することになる
- 「Self-Consistency 入れた方が良かった」「HyDE の方が retrieve 精度が高かった」を後から発見してリファクタが発生
- Anthropic / LangChain / OpenAI / 学術論文の用語が混在し、設計レビューで認識ズレ
- 既存エージェントの設計を他人 (将来の自分含む) に説明する時の共通語彙がない

### 2.1 Goals

- [ ] エージェントデザインパターンを **6 軸 × 約 50 パターン** で網羅的にカタログ化
- [ ] 各パターンに「既存リポジトリでの実装例」を明示し、後付け文書化を完成させる
- [ ] **代表 10 パターン** を最小サンプル実装 (各 200〜400 行) として `agent-patterns/` に配置
- [ ] サンプル間で **同一タスクの比較** ができる評価ハーネスを共通基盤として提供
- [ ] 新規エージェント追加時に「設計パターン早見表」として参照可能にする
- [ ] OSS 公開時に教材としても通用するクオリティ

### 2.2 Non-Goals

- **全パターンを実装する**: 50+ パターン全部実装は学習効率が悪い。10 パターンに絞る
- **既存エージェントのリファクタ**: 本 proposal では既存システムには手を入れない。設計の後付け命名のみ
- **LangChain / LangGraph 製品との API 互換**: あくまで素の Anthropic SDK / `llm-client` で実装する。フレームワーク依存しない
- **本番デプロイ**: `agent-patterns/` は **ローカル実行可能なサンプル集**。Cloud Run / Terraform は対象外
- **論文の完全リサーチサーベイ**: 学術論文の網羅的 review は目的ではなく、実用観点での整理を優先

---

## 3. Proposal

### 3.1 整理の 6 軸

| 軸 | 観点 | 何を決めるか |
|---|---|---|
| **A. 構造 (Architecture)** | エージェントの数と関係性 | 単一 / Workflow / Supervisor / Hierarchical / Swarm |
| **B. 制御フロー (Control Flow)** | 推論とアクションのループ形態 | ReAct / Plan-Execute / ReWoo / LATS |
| **C. 自己改善 (Self-Improvement)** | 出力品質を上げる繰り返し機構 | Reflection / Self-Refine / Cross-Check / CoVe |
| **D. メモリ (Memory)** | 何を覚え、いつ忘れるか | Short-term / Episodic / Semantic / Procedural |
| **E. 知識取得 (Retrieval / RAG)** | 外部知識をどう引くか | Naive / HyDE / Self-RAG / Hybrid / GraphRAG |
| **F. 協調・信頼性 (Collaboration & Reliability)** | 複数エージェント間 / 人との関係 | Debate / Voting / HITL / Guardrails |

各軸は独立で、実システムでは複数軸を組み合わせて使う。

### 3.2 A. 構造パターン (Architectural)

| # | パターン | 概要 | 既存実装例 |
|---|---|---|---|
| A1 | **Single Agent** | 1 エージェントが全ツールを持つ | Claude Agent SDK 既定 |
| A2-a | **Workflow Orchestrator** (決定論) | 固定 DAG / state machine。LLM は node として配置、「次の worker」はコードが決める | `tech-news-agent`, `stock-analysis-agent`, `lifeplanner-agent`, `driving-license-bot` |
| A2-b | **Supervisor / Orchestrator-Workers** (LLM 駆動) | 中央 LLM が動的に worker を選択。LangGraph 用語では Supervisor、Anthropic 用語では Orchestrator-Workers | `kanie-lab-agent`, `paper-qa-agent` (提案中) |
| A2-c | **Plan-then-Execute Orchestrator** | LLM が全計画を立てる → 決定論的に実行。実行中に LLM 判断は入らない | (未実装) |
| A3 | **Network / Peer-to-Peer** | sub-agent が相互通信、動的な役割交代 | (未実装、AutoGen GroupChat 相当) |
| A4 | **Swarm / Handoff** | アクティブな agent を動的に交代 | (未実装、OpenAI Swarm 相当) |
| A5 | **Sequential Chain** | A → B → C の固定列 (Workflow Orchestrator の最簡形) | `tech-news-agent` の RSS → 要約 → 配信 |
| A6 | **Map-Reduce / Parallel Fanout** | 並列 worker → 統合 | `tech-news-agent` の論文 batch ranking、`stock-analysis-agent` の universe screening |
| A7 | **Hierarchical** | Supervisor の入れ子 (多層) | (未実装) |

#### Orchestrator と Supervisor の関係 (用語整理)

```
Orchestrator (中央調整パターン総称)
├── A2-a. Workflow Orchestrator (決定論 / コード駆動)
│     固定 DAG / state machine。条件分岐は if-else やコード
│     例: LangGraph 固定エッジ, Airflow, AWS Step Functions
│
└── B. LLM-driven Orchestrator (動的 / LLM 駆動)
      ├── A2-b. Supervisor / Orchestrator-Workers
      │     supervisor LLM が dispatch、worker からの結果で next を決定
      │     FINISH 条件まで loop
      │
      ├── A2-c. Plan-then-Execute Orchestrator
      │     最初に LLM が全計画 → 決定論的に実行
      │
      └── A7. Hierarchical
            supervisor の中に sub-supervisor がいる多層構造
```

**結論**: Orchestrator は Supervisor を内包する上位概念。「決定論 Workflow Orchestrator」と「LLM 駆動 Supervisor」では実装も用途も異なるため、本カタログでは別パターンとして並べる。

### 3.3 B. 制御フロー (Control Flow)

| # | パターン | 概要 | 強み / 弱み |
|---|---|---|---|
| B1 | **ReAct** (Reason + Act) | Thought → Action → Observation を繰り返す | 既定の標準。柔軟だが long horizon で迷走 |
| B2 | **Plan-and-Execute** | 先に計画を全部立てる → 実行 | 長期タスクで脱線しにくい。計画ミスで全滅 |
| B3 | **ReWoo** (Reasoning WithOut Observation) | 計画と推論を完全分離、tool 結果は最後に統合 | トークン削減 (30〜50%)。動的応答が苦手 |
| B4 | **LATS** (Language Agent Tree Search) | MCTS で枝刈り探索 | 高精度。計算コストが桁違いに高い |
| B5 | **Reflexion Loop** | 失敗 → 反省 → 再試行 | 学習効果あり。memory 設計が要 |
| B6 | **Function Calling (Direct)** | LLM が JSON schema で tool 直接呼出 | 高速・低トークン。複雑推論に弱い |

### 3.4 C. 自己改善 (Self-Improvement)

| # | パターン | 概要 | 適用箇所 |
|---|---|---|---|
| C1 | **Self-Consistency** | 複数サンプリング → 多数決 | 数学・論理問題 |
| C2 | **Self-Refine** | 出力 → 自己批評 → 改稿 (同一モデル) | 文章生成、コード生成 |
| C3 | **Reflexion** | 失敗を memory に保存して次回参照 | 長期タスク学習 |
| C4 | **Cross-Check** (異モデル) | 別モデルで検証 (例: Claude × Gemini) | 高精度要件、`driving-license-bot` で実装済 |
| C5 | **Critic Agent** | 専任の批評エージェントを別建て | 出力品質の最終ゲート |
| C6 | **Chain-of-Verification (CoVe)** | 回答 → 検証質問生成 → 個別検証 → 統合 | hallucination 削減 |

### 3.5 D. メモリ (Memory)

| # | 種別 | 内容 | 保存先 |
|---|---|---|---|
| D1 | **Working / Short-term** | 単一セッション内の会話 | コンテキストウィンドウ |
| D2 | **Episodic** | 過去の対話イベント (時系列) | Firestore / Postgres |
| D3 | **Semantic** | ユーザー嗜好・事実知識 | pgvector / Cloud SQL |
| D4 | **Procedural** | 「こうやって解く」型の手順 | プロンプトに inject、または skill file |
| D5 | **Hierarchical Summary** | 古い対話を要約して圧縮 | LangMem / MemGPT |
| D6 | **Scratchpad** | ターン内の中間思考 | コンテキストウィンドウ (一時) |

### 3.6 E. 知識取得 (Retrieval / RAG)

| # | パターン | 概要 | 適合シーン |
|---|---|---|---|
| E1 | **Naive RAG** | embed → top-k → LLM | 基本形 |
| E2 | **HyDE** (Hypothetical Doc Embeddings) | 仮の回答を生成 → それを embed して検索 | クエリと文書のスタイルが乖離 |
| E3 | **Self-RAG** | 「retrieve するか」も LLM が判断 | 不要 retrieve のコスト削減 |
| E4 | **Corrective RAG (CRAG)** | retrieved を LLM が評価 → 信頼度低なら web 検索 | 知識網羅性が重要 |
| E5 | **Hybrid Retrieval** | BM25 + dense vector を RRF で合成 | 略語・固有名詞混在クエリ。`paper-qa-agent` で採用 |
| E6 | **Multi-hop / Iterative RAG** | 結果を見て次の query 生成 | 推論 chain が必要な質問 |
| E7 | **GraphRAG** | 知識グラフを構築・traverse | 関係性が重要なドメイン (citation, 法令) |
| E8 | **Contextual Compression** | retrieve → 関連箇所のみ抽出 → LLM | 長文文書 |
| E9 | **Parent-Child Chunking** | 小 chunk で検索 → 親 chunk で context 提供 | コード・論文 |

### 3.7 F. 協調・信頼性 (Collaboration & Reliability)

| # | パターン | 概要 | 既存実装例 |
|---|---|---|---|
| F1 | **Debate** | 複数 LLM が議論 → judge が裁定 | (未実装) |
| F2 | **Voting / Ensemble** | 並列実行して多数決 | (未実装) |
| F3 | **Round Robin** | 順番に発言 (AutoGen 系) | (未実装) |
| F4 | **Auction / Bid** | sub-agent がタスクへ入札、最高得点が担当 | (未実装) |
| F5 | **Human-in-the-Loop (HITL)** | 重要判断で人間確認 | `driving-license-bot` の question review UI |
| F6 | **Guardrails** | 入出力の事前/事後検査 | `security-platform` の DLP / injection 検出 |
| F7 | **Sandbox / Tool Pinning** | 実行環境隔離、tool 改ざん検知 | `security-platform` MCP Proxy |
| F8 | **Circuit Breaker / Rate Limit** | 暴走防止 | 各エージェントで個別実装 |
| F9 | **Computer Use / Browser Use** | GUI / Browser を直接操作 | (未実装) |

### 3.8 既存リポジトリでの実装状況マッピング (まとめ)

| パターン | 既存実装 |
|---|---|
| A1 Single Agent | (cli scripts のみ) |
| A2-a Workflow Orchestrator | `tech-news-agent`, `stock-analysis-agent`, `lifeplanner-agent`, `driving-license-bot` |
| A2-b Supervisor | `kanie-lab-agent`, `paper-qa-agent` (提案中) |
| A6 Map-Reduce | `tech-news-agent` の論文 batch ranking、`stock-analysis-agent` の universe screening |
| B1 ReAct | Claude Agent SDK 使用全エージェント |
| C4 Cross-Check (異モデル) | `driving-license-bot` (Gemini Generator × Gemini Reviewer) |
| D2 Episodic Memory | `piyolog-analytics`, `lifeplanner-agent` |
| D3 Semantic Memory (pgvector) | `driving-license-bot`, `fujisawa-platform`, `paper-qa-agent` (提案中) |
| E1 Naive RAG | `fujisawa-platform` を使う bot 群 |
| E5 Hybrid Retrieval | `paper-qa-agent` (提案中) |
| F5 HITL | `driving-license-bot` の review UI |
| F6 Guardrails | `security-platform` |
| F7 Sandbox / Tool Pinning | `security-platform` MCP Proxy |

**未実装で価値が高い**: A2-c Plan-then-Execute、A3 Network、A4 Swarm、B2/B3 Plan-Execute / ReWoo、C1/C2 Self-Consistency / Self-Refine、C6 Chain-of-Verification、E2/E3 HyDE / Self-RAG、E7 GraphRAG、F1 Debate

### 3.9 サンプル実装の推奨 10 パターン

学習・参照価値が高く、互いに重複が少ない 10 パターン。各 200〜400 行程度の最小実装。

| # | パターン | サンプルタスク | 主な学びポイント | 比較対象 |
|---|---|---|---|---|
| 1 | **A1 Single Agent** | 計算機 + Web 検索の 1 体エージェント | baseline。MCP / Agent SDK 抜きで素の API 呼出だけの最小実装 | 全パターンの比較対象 |
| 2 | **A2-a Workflow Orchestrator (決定論)** | RSS 取得 → 要約 → 配信パイプライン | 固定 DAG での agent 配置 | #3 |
| 3 | **A2-b Supervisor (LLM 駆動)** | リサーチタスクを LLM が動的分解 | 動的 dispatch の挙動 | #2, #4 |
| 4 | **A2-c Plan-then-Execute** | 同タスクの「計画→実行」分離 | Plan-Execute のトークン効率 | #3 |
| 5 | **A6 Map-Reduce** | 多文書要約 | 並列処理パターン、コスト・速度の差 | — |
| 6 | **C2 Self-Refine** | エッセイ生成 → 自己批評 → 改稿 | 単一モデル自己改善の費用対効果 | #7 |
| 7 | **C4 Cross-Check (異モデル)** | 数学問題を異モデルで判定 | `driving-license-bot` の薄い抜粋 | #6 |
| 8 | **C6 Chain-of-Verification** | 事実質問の hallucination 削減 | CoVe の効果定量化 | — |
| 9 | **E2 HyDE** | 論文タイトルから内容検索 | RAG 検索品質向上 | E1 Naive (内蔵比較) |
| 10 | **F1 Multi-Agent Debate** | 2 立場ディベート + 第三者 judge | 多エージェント協調・エンタメ性 | — |

**比較ポイント**: #2 / #3 / #4 で「決定論 Workflow / Supervisor / Plan-Execute」の同一タスク比較ができる構成。これは agentic system の中核で、最も学習価値が高い。

### 3.10 Notes / Constraints / Caveats

- **フレームワーク非依存**: LangChain / LangGraph / AutoGen 等の **製品依存はしない**。素の Anthropic SDK + `llm-client` (path dep) のみ
- **コスト管理**: 各サンプルは「実行コスト」を README に明記 (1 回 ¥XX 程度)。Claude Haiku 4.5 主体、Opus 4.7 を使うのは Cross-Check / Debate のみ
- **再現性**: `seed` 指定 + `temperature=0` のサンプルも併設し、回帰テスト可能に
- **テスト**: 各サンプルに `test_<pattern>.py` を必置。LLM 呼出は mock で代替 (本物の評価は週次 `make eval-real`)
- **トレース**: `analytics-platform` の JSONL イベントを emit。サンプル間でトークン消費・latency を比較可能に
- **モノレポ内に置く理由**: `llm-client` を path dep で流用できる、`analytics-platform` と連携可能、proposal リファレンスが直リンクできる

### 3.11 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 用語の解釈違いで実装と用語がブレる | Medium | 各サンプル README に「このサンプルが採用する厳密定義」を明記、論文・ブログへの参照 link 付与 |
| サンプル実装が toy 過ぎて参考にならない | Medium | 「既存エージェントとの対応関係」を各 README に書く。トイ実装 + 「本物はこう違う」セクション |
| パターンの優劣を誤解させる | Medium | 「このパターンが向かないケース」を必ず併記。比較表で trade-off を明示 |
| 学術用語のフォローが不完全 | Low | 主要論文のみ参照、二次資料 (Anthropic / Lilian Weng の blog) で代替 |
| サンプル間でコードスタイルがバラつく | Low | `agent-patterns/CONVENTIONS.md` で I/O 形式・命名・ファイル構成を統一 |
| 「結局どれ使えばいいの？」が分からない | High | `README.md` 冒頭に **decision tree** を配置 (「ユースケース → 推奨パターン」) |

---

## 4. Design Details

### 4.1 ディレクトリ構成

```
agent-patterns/                          ← 新規ディレクトリ
├── README.md                            ← カタログ index + 6 軸表 + decision tree
├── CONVENTIONS.md                       ← コードスタイル / I/O 規約
├── pyproject.toml                       ← uv workspace (llm-client path dep)
├── shared/
│   ├── __init__.py
│   ├── llm_client.py                    ← llm-client の thin wrap
│   ├── tools/
│   │   ├── calculator.py                ← 全サンプル共通の計算ツール
│   │   └── web_search.py                ← Brave Search MCP のラッパ
│   ├── eval/
│   │   ├── benchmark.py                 ← 共通評価ハーネス (latency / token / 精度)
│   │   └── tasks/
│   │       ├── research.yaml            ← #2/#3/#4 で共通利用するタスク定義
│   │       └── essay.yaml               ← #6 用
│   └── tracing/
│       └── analytics_emitter.py         ← analytics-platform への JSONL emit
├── 01_single_agent/
│   ├── README.md
│   ├── agent.py
│   ├── evaluate.py
│   └── test_agent.py
├── 02_workflow_orchestrator/
│   ├── README.md
│   ├── pipeline.py
│   ├── evaluate.py
│   └── test_pipeline.py
├── 03_supervisor/
├── 04_plan_then_execute/
├── 05_map_reduce/
├── 06_self_refine/
├── 07_cross_check/
├── 08_chain_of_verification/
├── 09_hyde/
└── 10_debate/
```

各サンプルディレクトリの中身:

```
NN_<pattern_name>/
├── README.md       ← パターン解説 / 何が学べるか / 既存エージェントとの対応 / 向かないケース
├── <impl>.py       ← 実装本体 (200〜400 行)
├── evaluate.py     ← shared/eval/benchmark.py を使った計測スクリプト
└── test_<impl>.py  ← unit test (LLM mock)
```

### 4.2 共通 README の構成 (各パターン)

```markdown
# <Pattern Name>

## 1 分で分かる説明
<3-4 行>

## このサンプルで学べること
- ...
- ...

## 実装の中核
<コード抜粋 + 解説>

## 既存エージェントでの実例
- `<agent>` の `<file>:<line>` でほぼ同じ構造を使っている

## 向かないケース
- ...

## 実行方法
```bash
uv run python evaluate.py
```

## 計測結果 (参考値)
| 指標 | 値 |
|---|---|
| latency p50 | ... |
| tokens (input/output) | ... |
| 推定コスト (1 回) | ¥... |

## 参照
- 論文: ...
- ブログ: ...
```

### 4.3 共通評価ハーネス

`shared/eval/benchmark.py`:

```python
from dataclasses import dataclass
from typing import Callable, Any
import time

@dataclass
class RunResult:
    output: Any
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_jpy: float
    metadata: dict

def run_with_metrics(
    fn: Callable,
    task: dict,
    label: str,
) -> RunResult:
    """共通の計測ラッパ。analytics-platform への emit も行う。"""
    start = time.monotonic()
    output = fn(task)
    elapsed = int((time.monotonic() - start) * 1000)
    # tokens / cost は llm_client の callback から取得
    ...
    return RunResult(...)
```

サンプル間で同じタスクを走らせた結果を `agent-patterns/README.md` の **比較表** に集約:

```markdown
## 同タスク (research.yaml) での比較

| パターン | latency p50 | total tokens | cost/run |
|---|---|---|---|
| #2 Workflow | 8s | 5.2k | ¥30 |
| #3 Supervisor | 14s | 12.8k | ¥95 |
| #4 Plan-Execute | 11s | 7.4k | ¥48 |
```

### 4.4 主要モジュール

#### `agent-patterns/01_single_agent/agent.py`

```python
"""Single Agent: 1 体のエージェントが全ツールを持つ baseline 実装。

- llm-client (Anthropic SDK 薄ラッパ) のみ依存
- フレームワーク (LangChain 等) は使わない
- tool は計算機 + Web 検索の 2 つだけ
"""
from llm_client import AnthropicClient
from shared.tools import calculator, web_search

def run(query: str) -> str:
    client = AnthropicClient(model="claude-sonnet-4-6")
    tools = [calculator.spec, web_search.spec]
    messages = [{"role": "user", "content": query}]

    for _ in range(10):  # max 10 iterations
        response = client.create_message(messages=messages, tools=tools)
        if response.stop_reason == "end_turn":
            return response.text
        # tool_use → 結果を messages に追加して loop
        ...
```

(各サンプルの具体実装は本 proposal の付録ではなく、実装 PR で詳細化)

### 4.5 Test Plan

- **Unit**:
    - 各サンプルの `test_<impl>.py` で `mock_llm_client` を使った動作確認
    - tool 呼出の順序が期待通りか
    - error path (tool 失敗、LLM タイムアウト) の挙動
- **Integration (実 API、CI からは除外)**:
    - `make eval-real` で全 10 サンプルを実 Claude API で実行、`agent-patterns/results.json` に記録
    - 週次手動実行を想定
- **Manual**:
    - 各 `README.md` の「実行方法」をその通り叩いて動くこと
    - `README.md` 比較表の数値が大幅に乖離しないこと (±50% 以内)

### 4.6 Migration / Rollback

- **新規ディレクトリのためマイグレーション不要**
- **既存エージェントには手を入れない**。設計の後付け命名は本 proposal の §3.8 で完結
- **ロールバック**: `agent-patterns/` ディレクトリ単独削除で完結。他システムへの影響なし

### 4.7 Feature Enablement

- `ANALYTICS_ENABLED=false` でトレース無効化可
- 各サンプルが Brave Search MCP を使う場合は `BRAVE_API_KEY` 任意 (未設定なら mock)
- LLM 呼出は `LLM_PROVIDER=anthropic` (既定) / `vertex_ai` を切替可

---

## 5. Operational Concerns

### 5.1 Monitoring

このシステムは runtime サービスではないので Cloud Logging / Push 通知は不要。代わりに:

- `agent-patterns/README.md` の **比較表** が最新値を保っているか定期確認 (月次)
- `make eval-real` の結果が大きく劣化していないか
- analytics-platform JSONL に各サンプルが `service_name=agent-patterns-<NN>` で emit する想定

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| サンプル実行が遅い | Claude API リトライ中の可能性 (`429`)。`ANTHROPIC_API_KEY` の rate limit を確認 |
| トークン消費が想定の 5 倍 | サンプルの max iterations が effective でない疑い。`<impl>.py` の loop guard を確認 |
| 比較表の latency が前回と乖離 | Claude モデルのバージョン更新の可能性。`AGENT_PATTERNS_MODEL=claude-sonnet-4-6@20250929` 等で pin |
| Brave Search が応答しない | MCP server local 起動 or `BRAVE_API_KEY` 設定漏れ |

### 5.3 Dependencies

| 依存 | 用途 |
|---|---|
| `llm-client` (path dep) | 全サンプルの LLM 呼出 |
| Anthropic SDK | LLM API |
| `analytics-platform` (path dep、optional) | トレース emit |
| Brave Search MCP (optional) | #1 / #9 で Web 検索 |
| `uv` | パッケージ管理 (モノレポ規約) |

### 5.4 Non-Functional Requirements

#### 性能 (Performance)
- 各サンプルの単発実行: 30 秒以内 (タイムアウト想定)
- `make eval-real` 全 10 サンプル: 10 分以内

#### コスト (Cost)
- `make eval-real` 1 回の総コスト: **¥500 以下** (Haiku 4.5 + Sonnet 4.6 主体、Opus 4.7 は最小限)
- 個別サンプル 1 回実行: ¥10〜100

#### プライバシー / データ保持
- PII を扱わない (学習用サンプルのため、入力タスクは固定 YAML)
- analytics-platform への emit は `service_name=agent-patterns-<NN>` で他システムと分離

#### キャパシティ
- N/A (個人ローカル実行が主)

---

## 6. Drawbacks

- **保守コスト**: Claude モデルがバージョンアップするたびに `make eval-real` の結果を更新する必要。少なくとも model 切替時 (Sonnet 4.6 → 4.7 等) は再計測
- **「結局どれ使うべき」の決定木が古びる**: 新しい論文・ブログでパターンが追加され続けるため、本 catalog は定期的に陳腐化する。半年〜1 年に 1 度の review が必要
- **モノレポを膨らませる**: agent サンプル 10 個でファイル数が 50+ 増える。`.gitignore` / workspace 設定の手当が必要
- **既存エージェントへの後付け命名が不正確になる可能性**: §3.8 のマッピングは「設計時に意識していたわけではない事後分類」。実装者の意図と合致しないケースがありえる
- **「サンプル ≠ 本番」のギャップ**: 200〜400 行の minimal 実装は production の複雑さを反映しない。それを誤解されると逆効果

## 7. Alternatives

### 案 A: ブログ記事として外部 (Zenn / Qiita) に書く
- 概要: モノレポ内には置かず、外部メディアで連載記事化する
- 却下理由: (1) `llm-client` / `analytics-platform` 等の path dep を使った再現が外部からはできない、(2) `kanie-lab-agent` 等の既存実装との対応リンクが切れる、(3) 個人運営の継続コストが増える。社内 (家族内) 学習教材としての価値が薄まる

### 案 B: フレームワーク (LangGraph) のサンプルをそのまま使う
- 概要: 自前で書かず LangGraph / AutoGen / OpenAI Swarm のチュートリアルへリンクする
- 却下理由: (1) フレームワーク固有のお作法に縛られる、(2) 既存エージェント (素の Claude Agent SDK 主体) との対応が取りづらい、(3) 「素の実装で理解する」学習価値が失われる

### 案 C: 既存エージェントをリファクタしてパターン化する
- 概要: 新規ディレクトリではなく、既存エージェントを「教科書的に」書き直す
- 却下理由: (1) 既存エージェントは production 都合の複雑さがあって教科書には不向き、(2) リファクタの工数とリスクが大きい、(3) 「サンプル」としての独立性が失われる

### 案 D: 10 パターンではなく 4〜5 パターンに絞る
- 概要: A1 / A2-a / A2-b / C2 / C4 だけ実装 (Workflow / Supervisor / Self-Refine / Cross-Check 中心)
- 検討: 工数削減の観点では妥当。ただし「Plan-then-Execute との比較」「HyDE の効果」「Debate のエンタメ性」を欠くと学習教材としては片手落ち
- **採用検討**: 本 proposal は 10 パターン記載を維持するが、**実装の優先順位を以下に明示**:
    - **Tier 1 (Phase 1)**: #1 / #2 / #3 / #4 (構造比較の中核)
    - **Tier 2 (Phase 2)**: #6 / #7 (Self-Improvement の中核)
    - **Tier 3 (Phase 3)**: #5 / #8 / #9 / #10 (応用)

### 案 E: 各サンプルを別リポジトリにする
- 概要: パターンごとに小リポジトリを分割
- 却下理由: 比較表 / 共通評価ハーネスが分散する。`llm-client` 流用も path dep が使えない

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-24 | Draft | 初稿 (Claude Code との設計セッション経由) |
