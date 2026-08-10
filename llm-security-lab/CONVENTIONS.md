# llm-security-lab CONVENTIONS

各章 (Phase 1-10) の実装で守るべきファイル構成・命名規約・notebook style。 PROPOSAL-0008 §3.2 / §3.3 を実装ルールとして展開したもの。

## ディレクトリ構成テンプレート

各章は以下の構成にする (`NN` は 01〜10 のゼロ埋め、 `<name>` は OWASP 公式名の kebab-case):

```
NN_<name>/
├── README.md                      ← 必須、 §3.3 共通フォーマット (後述)
├── vulnerable_app/                ← FastAPI app、 意図的に脆弱
│   ├── main.py                    ← 共通 API 規約 (proposal §4.2) に準拠
│   ├── Dockerfile
│   └── requirements 系は pyproject 経由 (uv)
├── attacks/                       ← 攻撃シナリオ
│   ├── <scenario_a>.yaml          ← DeepTeam config
│   ├── <scenario_b>.py            ← PyRIT / 手書き script
│   └── ...
├── defenses/                      ← 段階的防御
│   ├── v1_<short_name>.py
│   ├── v2_<short_name>.py
│   └── v3_<short_name>.py
├── notebook.ipynb                 ← walkthrough (1 章 = 1 notebook)
└── tests/
    └── test_defenses.py           ← 防御 v1/v2/v3 単体テスト + 正常 prompt 100 件 (proposal §3.10.1)
```

## 命名規約

- ディレクトリ名: `NN_<kebab>` (例: `01_prompt_injection`、 `07_system_prompt_leakage`)
- 攻撃 file: `<scenario>.yaml` (DeepTeam) / `<scenario>.py` (PyRIT・手書き)。 scenario name は **動詞 + 名詞** の組み合わせ推奨 (例: `direct_injection.yaml`、 `crescendo_multi_turn.py`)
- 防御 file: `v<N>_<short_name>.py` (例: `v1_system_prompt_hardening.py`、 `v2_input_filter.py`、 `v3_layered.py`)
- defense version 規約:
    - **v0**: 防御なし、 vulnerable app そのまま (`vulnerable_app/main.py` そのまま)
    - **v1**: 最低限の対策 1 段
    - **v2**: v1 + 追加対策 (典型例: 入力 / 出力フィルタ)
    - **v3**: 多層防御 (input + output + rate limit 等)
- notebook file: 各章ディレクトリの `notebook.ipynb` (1 章 1 つ)、 もしくは `notebooks/NN_<name>.ipynb` (横断 notebook 用)

## 共通 API 規約 (vulnerable_app)

全章の `vulnerable_app/main.py` は以下を満たす。 防御版は同インターフェースを差し替え実装する (proposal §4.2):

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class QueryRequest(BaseModel):
    message: str
    system_prompt: str | None = None  # LLM07 等で利用
    context: list[str] | None = None  # RAG 系 (LLM01 indirect, LLM08)

class QueryResponse(BaseModel):
    answer: str
    tool_calls: list[dict] | None = None  # LLM06 で利用
    metadata: dict

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    ...

@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
```

## README.md の構成 (各章 README、 6 セクション必須)

```markdown
# NN. <脆弱性名> (OWASP LLM NN: <英名>)

## 1. 攻撃概要 (Overview)
- OWASP 公式定義 (引用)
- なぜ怖いか / 実世界での事例
- 本章で扱う攻撃面のスコープ

## 2. 攻撃方法 (Attack Methods)
- 攻撃シナリオ A (攻撃の流れ / 使用 probe / 期待される v0 成功率)
- 攻撃シナリオ B
- ...

## 3. 防御策 (Defenses)
- v0 (no defense): vulnerable app そのまま、 baseline
- v1: <最低限の対策> (何をやる / なぜ効く / 何が防げない / 実測 v1 成功率)
- v2: <追加対策>
- v3: <多層防御>

## 4. 残存リスクと運用での補完
- v3 でも防げない攻撃と、 その理由
- production agent (本 monorepo の各 agent) でどう補完するか
- production への持ち込み判断 (proposal §3.10 の 6 基準に照らした結果)

## 5. 実行方法
\`\`\`bash
make setup-NN
make attack-NN          # 全 v0 で実行
make defend-NN VER=v3   # v3 で実行
\`\`\`
notebook.ipynb で walkthrough。

## 6. 参照
- OWASP 公式ページ
- DeepTeam / PyRIT ドキュメント該当箇所
- promptme の対応 challenge (参考にした場合)
- 関連論文・dataset (例: PoisonedRAG / vec2text)
```

## Notebook style

- **1 notebook = 15〜20 cell** が上限。 長くなりそうなら複数に分割
- 各 cell の先頭に **Markdown でその cell の目的** を 1-2 行記述
- 攻撃成功率の数値を表示する cell は **3 回実行して再現性を確認** (regression mode + stochastic mode 両方 / proposal §4.6)
- 出力に LLM raw response (jailbreak 成功時の問題発言を含む可能性あり) を載せる場合は **truncate + 「機微なため省略」 注記**

## 攻撃 target ガードレール (Phase 0c 以降必須)

DeepTeam / PyRIT / 手書き script のいずれも、 `shared/attacks/_target_guard.py` の `validate_target(url)` で attack target を allowlist 検証する:

- 許容: `localhost`, `127.0.0.1`, `vulnerable-app-NN` (Docker service 名), `ollama` (Docker service 名)
- 拒否: その他 (cloud-run.app, github.com 等の外部 endpoint は ValueError)
- override: `LAB_ALLOW_EXTERNAL_TARGET=true` env で allowlist を緩める (自己責任、 起動時警告)

## ロギング・成果物

- 攻撃結果: `results/<chapter>/<defense_version>_<timestamp>.json` (集計可能形式)
- ノートブック生出力: git commit 対象外 (`.gitignore` で除外)
- analytics-platform への emit は行わない (本ラボは production 計装層と独立、 proposal §5.4)
