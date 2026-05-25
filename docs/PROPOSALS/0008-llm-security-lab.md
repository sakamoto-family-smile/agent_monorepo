# PROPOSAL-0008: OWASP LLM Top 10 体験学習ラボ `llm-security-lab/`

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-24 |
| **Updated** | 2026-05-24 |
| **Target** | `llm-security-lab/` (新規ディレクトリ、教材) |
| **Related PRs** | (none yet、本 PR が初版) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

OWASP LLM Top 10 (2025) の 10 種類の脆弱性について、**「攻撃を体感し、防御の効果を定量的に測る」** ハンズオン教材を monorepo 内 `llm-security-lab/` に整備する。各脆弱性で **意図的に脆弱な FastAPI アプリ + 攻撃シナリオ + 段階的防御 (v1〜v3) + Jupyter notebook** を提供し、`make attack-01 / make defend-01` 形式で学習者がローカルで完結して体験できる構成にする。

LLM ランタイムは **Ollama (既定、ローカル完結) + Vertex AI Claude (比較用、optional)**、Red Team ツールは **DeepTeam (主軸) + PyRIT (multi-turn 攻撃専用に併用)**、Notebook 環境は **JupyterLab**。

`security-platform` とは意図的に独立させ、重複を許容する。本ラボで実証された防御パターンを将来 `security-platform` に持ち込む可能性は留保する。

## 2. Motivation

### 現状の課題

monorepo は production agent システムが 6 つあり、`security-platform/` で MCP Proxy / DLP / CVE 監視等の **横断防御層** を運用している。しかし以下のギャップがある:

1. **OWASP LLM Top 10 (2025) の各項目が何で、なぜ怖いかを実体験する場がない**: `security-platform` の Promptfoo 設定 (`redteam.yaml`) を見ても「LLM01 Prompt Injection」が抽象的にしか分からない。攻撃が成功する瞬間と防御で食い止まる瞬間を見ないと理解が定着しない
2. **未実装防御の比較検証ができない**: LLM04 (Data Poisoning) / LLM07 (System Prompt Leakage) / LLM09 (Misinformation) は monorepo に対応実装がなく、設計判断の根拠が経験ベースに留まる
3. **新メンバー / 将来の自分への教育コストが高い**: 「なぜ MCP Proxy で input filter / output validator を入れたか」を製品コードから読み取るのは困難
4. **個人運営なのにセキュリティ判断の根拠が散在**: PROPOSAL-0002 (DeepTeam 移行) や `security-platform/docs/DESIGN.md §5.3` 等に分散しており、横串で「何が防げて何が防げないか」を一覧できない

### 放置するとどうなるか

- 新規 agent 追加時に LLM07 (System Prompt Leakage) 対策を忘れる、等の **ヒューマンエラー**
- production の `security-platform` 機能追加判断 (「LLM09 用に CoVe 入れるべきか？」) を data なしで意思決定
- `paper-qa-agent` / `lifeplanner-agent` 等で扱う PII / 機密データへの攻撃面の理解が浅いまま運用継続

### 2.1 Goals

- [ ] OWASP LLM Top 10 (2025) 全 10 項目それぞれに「vulnerable app + attack + defense (v1〜v3) + notebook」を整備
- [ ] 各章で **攻撃成功率の段階的低下** が定量化される (例: v0 80% → v1 60% → v2 25% → v3 5%)
- [ ] 学習者が `git clone` + `docker compose up` + `jupyter lab` で 5 分以内に動かせる
- [ ] **LLM ランタイムは Ollama 既定でクラウドコストゼロ** (Vertex 切替は optional)
- [ ] 各章の README で **攻撃概要 / 攻撃方法 / 防御策** を OWASP 公式定義 + 実例 + 自分の言葉で記述
- [ ] DeepTeam の YAML / PyRIT の Python script として **再利用可能な攻撃資産** を蓄積
- [ ] 全章完了後、`security-platform` 側へ「持ち込む価値のある防御パターン」を別 proposal として起票

### 2.2 Non-Goals

- **production への直接導入**: `llm-security-lab/` は学習教材であり、`security-platform` のような production 防御層は別物。将来の持ち込みは別 proposal で
- **`security-platform` への直接依存**: 意図的にコード重複を許容し、独立して動く構成にする。学習材料としての readability 優先
- **OSS リポジトリとしての公開**: monorepo 内に閉じる。promptme のような独立 OSS は目指さない (ただし内部資料として完成度は高く保つ)
- **全 OWASP 項目を 1 PR で実装**: 10 PR に分割。共通基盤を Phase 0 で先に PR、各項目を Phase 1〜10 で 1 PR ずつ
- **Training-time attack の実演**: LLM04 (Data Poisoning) は **RAG 経由 (inference-time) の poisoning のみ実演**、training 攻撃は対象外と明示
- **モデル fine-tuning / RLHF レベルの防御**: Llama Guard / 入出力フィルタ / system prompt hardening 等の **application 層の防御のみ**
- **本番 cloud デプロイ**: 全てローカル (Docker Compose) で完結

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: 「LLM01 Prompt Injection を体感する」

> 学習者は `llm-security-lab/` を clone し、`make setup-01` で 01 章の vulnerable app と Ollama (mistral) を起動。`jupyter lab notebooks/01_prompt_injection.ipynb` を開き、Cell を順に実行する。
>
> - Cell 1: 普通のリクエスト → 期待通りの応答
> - Cell 2: DeepTeam で attack 25 回実行 → 攻撃成功率 80%
> - Cell 3: `defenses/v1_system_prompt_hardening.py` を有効化 → 攻撃成功率 60%
> - Cell 4: `defenses/v2_input_filter.py` (Llama Guard) を追加 → 攻撃成功率 25%
> - Cell 5: `defenses/v3_layered.py` (input + output + rate limit) を有効化 → 攻撃成功率 5%
> - Cell 6: 「v3 でも 5% 残る攻撃は何か」を分析、`README.md §残存リスク` を参照

#### 3.1.2 ストーリー 2: 「production agent の設計判断材料を得る」

> 開発者は `paper-qa-agent` に LLM07 (System Prompt Leakage) 対策を入れるか検討。`07_system_prompt_leakage/notebook.ipynb` を実行し、PyRIT の Crescendo attack で system prompt が抽出できることを確認。`defenses/v2_prompt_isolation.py` の効果 (抽出成功率 90% → 15%) を見て、`paper-qa-agent` への持ち込みを意思決定。

### 3.2 ディレクトリ構造

```
llm-security-lab/
├── README.md                           ← OWASP Top 10 マッピング + 学習順序 + 章別 index
├── CONVENTIONS.md                      ← 各章のファイル構成・命名規約・notebook の書き方
├── pyproject.toml                      ← uv workspace, llm-client path dep
├── docker-compose.yml                  ← Ollama + 全章の vulnerable app
├── Makefile                            ← make setup-NN / attack-NN / defend-NN / eval-all
├── notebooks/                          ← JupyterLab 起点
│   └── 00_index.ipynb                  ← 章間ナビゲーション
├── shared/                             ← Phase 0 で実装
│   ├── llm_runtime/
│   │   ├── ollama_client.py            ← ローカル LLM (既定)
│   │   ├── vertex_client.py            ← Vertex Claude (optional 比較用)
│   │   └── runtime.py                  ← LLM_RUNTIME env で切替
│   ├── attacks/
│   │   ├── deepteam_runner.py          ← DeepTeam YAML → 実行
│   │   ├── pyrit_runner.py             ← PyRIT multi-turn runner
│   │   └── manual_runner.py            ← 手書き Python script の共通実行枠
│   ├── defenses/
│   │   ├── prompt_armor.py             ← system prompt hardening helper
│   │   ├── input_filter.py             ← Llama Guard / regex フィルタ共通
│   │   ├── output_validator.py         ← JSON schema 検証 + XSS sanitize
│   │   └── rate_limit.py               ← in-memory rate limiter
│   └── eval/
│       ├── attack_success_rate.py      ← 攻撃成功率測定
│       ├── token_cost.py               ← Vertex 切替時のコスト計測
│       └── reporter.py                 ← 章別結果 JSON 出力
├── 01_prompt_injection/                ← Phase 1
│   ├── README.md                       ← 攻撃概要 / 攻撃方法 / 防御策
│   ├── vulnerable_app/
│   │   ├── main.py                     ← FastAPI、意図的に脆弱
│   │   └── Dockerfile
│   ├── attacks/
│   │   ├── direct_injection.yaml       ← DeepTeam config
│   │   ├── indirect_via_rag.py
│   │   └── crescendo_multi_turn.py     ← PyRIT
│   ├── defenses/
│   │   ├── v1_system_prompt_hardening.py
│   │   ├── v2_input_filter.py
│   │   └── v3_layered.py
│   ├── notebook.ipynb                  ← 攻撃 → 防御の walkthrough
│   └── tests/
│       └── test_defenses.py
├── 02_sensitive_information_disclosure/   ← Phase 2
├── 03_supply_chain/                       ← Phase 3 (静的解析中心)
├── 04_data_and_model_poisoning/           ← Phase 4 (RAG poisoning 実演のみ)
├── 05_improper_output_handling/           ← Phase 5
├── 06_excessive_agency/                   ← Phase 6
├── 07_system_prompt_leakage/              ← Phase 7
├── 08_vector_and_embedding_weaknesses/    ← Phase 8
├── 09_misinformation/                     ← Phase 9
└── 10_unbounded_consumption/              ← Phase 10
```

### 3.3 各章 README の構成 (共通フォーマット)

```markdown
# NN. <脆弱性名> (OWASP LLM NN: <英名>)

## 1. 攻撃概要 (Overview)
- OWASP 公式定義 (引用)
- なぜ怖いか / 実世界での事例
- 本章で扱う攻撃面のスコープ

## 2. 攻撃方法 (Attack Methods)
- 攻撃シナリオ A (例: 直接プロンプト注入)
  - 攻撃の流れ
  - DeepTeam / PyRIT のどの probe を使うか
  - 期待される攻撃成功率 (vulnerable app に対して)
- 攻撃シナリオ B (例: 間接プロンプト注入 via RAG)
  - ...

## 3. 防御策 (Defenses)
- v0 (no defense): vulnerable app そのまま
- v1: <最低限の対策>
  - 何をやる / なぜ効く / 何が防げない
  - 攻撃成功率 (実測)
- v2: <追加対策>
- v3: <多層防御>

## 4. 残存リスクと運用での補完
- v3 でも防げない攻撃と、その理由
- production (本 monorepo の各 agent) でどう補完するか

## 5. 実行方法
```bash
make setup-NN
make attack-NN          # 全 v0 で実行
make defend-NN VER=v3   # v3 で実行
jupyter lab notebooks/NN_<name>.ipynb
```

## 6. 参照
- OWASP 公式ページ
- DeepTeam ドキュメント該当箇所
- promptme の対応 challenge (参考にした場合)
- 関連論文
```

### 3.4 OWASP LLM Top 10 × 章マッピング

| 章 | OWASP # | 名前 | 主な攻撃ツール | 主な防御アプローチ |
|---|---|---|---|---|
| 01 | LLM01 | Prompt Injection | DeepTeam + PyRIT (Crescendo) | system prompt hardening / Llama Guard / input filter / 多層 |
| 02 | LLM02 | Sensitive Information Disclosure | DeepTeam | output redaction / PII scrubber / log sanitization |
| 03 | LLM03 | Supply Chain | 静的解析 (Snyk, gitleaks) | 依存 pinning / SBOM / MCP server hash |
| 04 | LLM04 | Data and Model Poisoning | RAG 経由 poisoning script | corpus 整合性 hash / 参照元 trust score / freshness check |
| 05 | LLM05 | Improper Output Handling | DeepTeam (XSS / SSRF via LLM output) | output schema validation / HTML sanitize / URL allowlist |
| 06 | LLM06 | Excessive Agency | DeepTeam (agentic tool abuse) | tool whitelisting / scope minimization / approval gate |
| 07 | LLM07 | System Prompt Leakage | PyRIT (多段抽出) | prompt isolation / secret 別管理 / detection rule |
| 08 | LLM08 | Vector and Embedding Weaknesses | RAG poisoning + embedding inversion | provenance check / embedding signing / outlier 検出 |
| 09 | LLM09 | Misinformation | hallucination ベンチ (TruthfulQA 抜粋) | Chain-of-Verification / retrieval 必須化 / confidence threshold |
| 10 | LLM10 | Unbounded Consumption | 無限 prompt / loop / 巨大 context | rate limit / token budget / max iterations / circuit breaker |

### 3.5 Red Team ツール選定

| ツール | 担当章 | 理由 |
|---|---|---|
| **DeepTeam** | 01, 02, 05, 06, 09, 10 (主軸) | Python ネイティブ、OWASP マッピング公式、PROPOSAL-0002 とも整合 |
| **PyRIT** | 01 (Crescendo), 07 (System Prompt Leakage 多段抽出) | Multi-turn 攻撃が本家、「複数ターンで段階的に jailbreak する怖さ」を体感させる |
| **手書き Python script** | 04 (RAG poisoning), 08 (embedding inversion) | 既存ツールに該当 probe がない / 自前実装の方が教材として明快 |
| **静的解析 (Snyk / gitleaks)** | 03 (Supply Chain) | red team ツールの対象外領域 |

### 3.6 LLM ランタイム

| ランタイム | 既定 / optional | モデル例 | 用途 |
|---|---|---|---|
| **Ollama** | 既定 | mistral / llama3 / sqlcoder / granite | 全章のローカル実行 |
| **Vertex AI Claude** | optional | claude-haiku-4-5 / claude-sonnet-4-6 | 比較学習用 (`LLM_RUNTIME=vertex` で切替) |
| **`llm-client` (path dep)** | 内部 wrap | (両者を抽象化) | monorepo 規約準拠 |

「OSS LLM では効く攻撃が Claude には効かないか？」を体感できる構成。

### 3.7 Phase ロードマップ (PR 分割)

| Phase | PR | 内容 | 工数目安 |
|---|---|---|---|
| **Phase 0** | PR-A | 共通基盤: `shared/` / `docker-compose.yml` / `Makefile` / `README.md` / DeepTeam runner / PyRIT runner / Ollama client / eval harness | 1〜2 週 |
| **Phase 1** | PR-1 | 01_prompt_injection (最重要、他章の参照実装) | 1〜2 週 |
| **Phase 2** | PR-2 | 02_sensitive_information_disclosure | 1 週 |
| **Phase 3** | PR-3 | 03_supply_chain (静的解析中心、軽量) | 0.5 週 |
| **Phase 4** | PR-4 | 04_data_and_model_poisoning | 1.5 週 |
| **Phase 5** | PR-5 | 05_improper_output_handling | 1 週 |
| **Phase 6** | PR-6 | 06_excessive_agency (agent との結合あり、重め) | 1.5 週 |
| **Phase 7** | PR-7 | 07_system_prompt_leakage (PyRIT 統合) | 1.5 週 |
| **Phase 8** | PR-8 | 08_vector_and_embedding_weaknesses | 1.5 週 |
| **Phase 9** | PR-9 | 09_misinformation (CoVe 実装) | 1.5 週 |
| **Phase 10** | PR-10 | 10_unbounded_consumption | 1 週 |
| **Phase 11** | PR-X | (optional) `security-platform` への持ち込み別 proposal 起票 | — |

各 Phase は独立しており、Phase 0 完了後は **任意の順序で並行進行可能**。優先度ベースで Phase 1 → 7 → 6 → 9 → 02 → 10 → 05 → 04 → 08 → 03 の順を推奨 (production agent への影響度順)。

### 3.8 Notes / Constraints / Caveats

- **`security-platform` と意図的に独立**: 同じ防御パターン (rate limit / input filter / output validator) を別実装する。学習教材としての readability を優先し、production 都合の複雑さを持ち込まない
- **promptme の参照範囲**: アイデア・攻撃シナリオの構成は参考にするが、コードは独自実装 (Flask → FastAPI、pip → uv、Python 3.10 → 3.12)。各 README で「参考にした promptme challenge」を出典明記
- **Notebook のセル数を抑える**: 1 notebook = 15〜20 cell を上限。長いものは複数に分割
- **攻撃成功率の再現性**: LLM 出力の非決定性により実測値はブレる。`seed` 指定 + `temperature=0` のサンプルも併設し、回帰テスト可能に
- **Vertex 切替時のコスト**: `LLM_RUNTIME=vertex` で全章実行すると ~¥500/月 程度 (Haiku 4.5 想定)。README で警告
- **PyRIT の Azure 依存**: PyRIT 本体は Azure OpenAI に最適化されているが、Ollama / Vertex 経由でも使える (target adapter を薄く書く)
- **LLM03 Supply Chain の例外性**: 他の章と異なり「LLM 出力を攻撃する」のではなく「依存パッケージ / モデル配布経路」が対象。教材としては軽め (vulnerable app は notebook 1 つで完結)
- **LLM04 Data Poisoning の限定スコープ**: training 攻撃は教材化が困難 (実モデル fine-tune が必要)。**RAG 経由の inference-time poisoning に限定**することを README で明示
- **JupyterLab の起動方法**: `make jupyter` で `docker compose run --service-ports jupyter` を起動。ホスト Python 環境を汚さない

### 3.9 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 教材が toy 過ぎて参考にならない | Medium | 各 README に「production (`paper-qa-agent` 等) ではこう違う」セクションを必置 |
| 攻撃成功率の数値が再現しない | Medium | `seed` 固定 + `temperature=0` の "regression mode" を併設、ブレ幅を README に明記 |
| OWASP 公式の改訂に追従できない | Low | カタログ部分は §3.4 のみに集約、年次レビューを Implementation History に記載 |
| DeepTeam / PyRIT の breaking change | Medium | `uv.lock` で version pinning、CI で週次互換性チェック |
| 学習者が悪用する | Medium | README 冒頭に「**個人ローカル環境での学習目的のみ**、他者システムへの無断試行は禁止」を明示。OSS 公開はしない |
| Ollama モデル容量で disk 圧迫 | Low | mistral (4GB) / llama3 (4.7GB) / llama-guard (4.7GB) の合計 ~15GB。README に明記、`make clean-models` 用意 |
| `security-platform` との重複コードが drift する | Medium | コードは drift して OK (学習用なので)。**設計の drift は Phase 11 で別 proposal で吸収** |
| 月額コストが見えにくい | Low | `make eval-all RUNTIME=vertex` 実行前にコスト見積もりを表示 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
                    ┌────────────────┐
                    │  JupyterLab    │  ← 学習者の入口
                    │ (notebook UI)  │
                    └───────┬────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │ shared/  │  │ NN_xxx/  │  │ shared/  │
       │ attacks/ │  │vulnerable│  │ defenses/│
       │          │  │   _app/  │  │          │
       └─────┬────┘  └─────┬────┘  └─────┬────┘
             │             │              │
             │       ┌─────▼───────┐      │
             └──────▶│ FastAPI     │◀─────┘
                     │ (各章 toy)   │
                     └─────┬───────┘
                           │
                  ┌────────▼─────────┐
                  │ shared/llm_      │
                  │ runtime/         │
                  │  ├ ollama        │  ← 既定
                  │  └ vertex_claude │  ← optional
                  └────────┬─────────┘
                           │
                   ┌───────▼────────┐
                   │ Ollama / Vertex│
                   │ AI Claude      │
                   └────────────────┘

   ┌─────────────────────────────────────┐
   │ shared/eval/                        │ ← 攻撃成功率・cost・latency を集約
   │  → results/NN_<name>_<version>.json │
   └─────────────────────────────────────┘
```

### 4.2 共通 API 規約

各 vulnerable app は同じインターフェースで実装する (notebook から横断的に呼べるように):

```python
# llm-security-lab/NN_<name>/vulnerable_app/main.py
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class QueryRequest(BaseModel):
    message: str
    system_prompt: str | None = None  # 一部 vuln app は受け入れる (LLM07 等)
    context: list[str] | None = None  # RAG 系で利用 (LLM01 indirect, LLM08)

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

防御版は同じインターフェースで `/query` を上書きする (差し替え透過)。

### 4.3 共通評価ハーネス

```python
# shared/eval/attack_success_rate.py
@dataclass
class AttackResult:
    attack_id: str
    chapter: str          # "01_prompt_injection"
    defense_version: str  # "v0" | "v1" | "v2" | "v3"
    success: bool
    response_text: str
    metadata: dict        # token usage, latency, etc.

def aggregate(results: list[AttackResult]) -> dict:
    """章別 × defense version 別の成功率を集計し、JSON で出力。"""
    ...
```

集計結果は `results/<chapter>/<version>_<timestamp>.json` に保存。`make report-all` で全章を表形式で集約:

```
| 章                       | v0  | v1  | v2  | v3  |
|--------------------------|-----|-----|-----|-----|
| 01_prompt_injection      | 80% | 60% | 25% |  5% |
| 02_sensitive_info        | 65% | 40% | 15% |  3% |
| ...
```

### 4.4 Docker Compose 構成 (Phase 0)

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports: ["11434:11434"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s
      timeout: 5s
      retries: 5

  jupyter:
    build:
      context: .
      dockerfile: shared/Dockerfile.jupyter
    volumes:
      - .:/workspace
    ports: ["8888:8888"]
    environment:
      - JUPYTER_TOKEN=${JUPYTER_TOKEN:-localdev}
      - OLLAMA_HOST=http://ollama:11434
    depends_on:
      ollama:
        condition: service_healthy

  # 各章の vulnerable app は profile で起動制御
  vulnerable-app-01:
    profiles: ["chapter-01", "all"]
    build: ./01_prompt_injection/vulnerable_app
    environment:
      - OLLAMA_HOST=http://ollama:11434
      - MODEL=mistral
    ports: ["8001:8000"]
    depends_on:
      ollama:
        condition: service_healthy

  # 02 〜 10 同様
```

`docker compose --profile chapter-01 up` で 01 章だけ起動、`--profile all` で全章起動。

### 4.5 Makefile (主なターゲット)

```makefile
.PHONY: setup-all setup-NN attack-NN defend-NN eval-all clean

setup-all:
	docker compose --profile all up -d
	docker compose exec ollama ollama pull mistral
	docker compose exec ollama ollama pull llama-guard-3-8b

setup-01:
	docker compose --profile chapter-01 up -d

attack-01:
	cd 01_prompt_injection && uv run python -m shared.attacks.deepteam_runner --config attacks/direct_injection.yaml

defend-01:
	cd 01_prompt_injection && DEFENSE_VERSION=$(VER) docker compose restart vulnerable-app-01
	$(MAKE) attack-01

eval-all:
	uv run python -m shared.eval.reporter --output results/

jupyter:
	docker compose up jupyter

clean:
	docker compose down -v

clean-models:
	docker compose exec ollama ollama rm mistral llama3 llama-guard-3-8b
```

### 4.6 Test Plan

- **Unit (各章 + shared)**:
    - `shared/attacks/deepteam_runner.py`: mock DeepTeam result で aggregate 関数の正当性
    - `shared/defenses/input_filter.py`: 既知の jailbreak prompt で reject されることを確認
    - `shared/eval/attack_success_rate.py`: aggregate 計算の境界値テスト
    - 各章 `tests/test_defenses.py`: 防御 v1/v2/v3 が個別に動くこと
- **Integration (実 LLM、CI からは除外)**:
    - `make eval-all` を実 Ollama で実行、`results/` に出力
    - GitHub Actions 上は mock LLM で smoke test、本実行は週次手動 `make eval-real`
- **Manual / E2E**:
    - 各章の notebook を JupyterLab で順に実行、全 cell が成功すること
    - `README.md` の手順だけで learning experience が完結すること
    - 攻撃成功率の数値が ±20% 以内で再現すること (3 回試行の中央値)

### 4.7 Migration / Rollback

- **新規ディレクトリのためマイグレーション不要**
- **既存システムには影響なし** (`security-platform` 含む、意図的に独立)
- **ロールバック**: `llm-security-lab/` ディレクトリ単独削除で完結
- **Phase 単位の rollback**: 各章は独立 PR なので、特定章のみ revert 可能

### 4.8 Feature Enablement

各章の vulnerable app は `DEFENSE_VERSION` env で防御レベルを切替:

| env | 値 | 効果 |
|---|---|---|
| `DEFENSE_VERSION` | `v0` (既定) | 防御なし、攻撃成功 baseline |
| | `v1` | system prompt hardening のみ |
| | `v2` | v1 + 入力フィルタ |
| | `v3` | v2 + 出力検証 + rate limit |
| `LLM_RUNTIME` | `ollama` (既定) | ローカル Ollama |
| | `vertex` | Vertex AI Claude (要 ADC + コスト) |
| `OLLAMA_MODEL` | `mistral` (既定) | mistral / llama3 / sqlcoder / granite |
| `JUPYTER_TOKEN` | `localdev` (既定) | JupyterLab 認証トークン |

---

## 5. Operational Concerns

### 5.1 Monitoring

学習教材なので runtime 監視は不要。代わりに:

- `results/` 配下の集計結果が **章追加・防御更新のたびに更新** されているか手動確認
- `make eval-all` 実行で全体の数値が大きく劣化していないか (回帰チェック)
- DeepTeam / PyRIT の breaking change 検知は CI の week 1 回の `make eval-real`

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| Ollama が起動しない | `docker compose logs ollama` で確認、model pull が完了しているか |
| 攻撃成功率が想定と乖離 | (1) モデルバージョン変更の可能性、(2) `seed` / `temperature` 設定確認、(3) DeepTeam バージョン更新の可能性 |
| `make eval-all` が遅い | Ollama は単一 instance なので並列度上げ過ぎると逆効果。`MAX_PARALLEL=2` を推奨 |
| JupyterLab に接続できない | `JUPYTER_TOKEN` env を確認、`docker compose logs jupyter` |
| Vertex 切替時に 429 | Vertex AI quota 不足。`VERTEX_REGION` を変更 or リトライ |
| disk 容量不足 | `make clean-models` で Ollama モデル削除 |

### 5.3 Dependencies

| 依存 | 用途 | バージョン |
|---|---|---|
| Python | 言語 | 3.12+ |
| uv | パッケージ管理 | latest |
| Docker / Docker Compose | 実行環境 | 24+ |
| Ollama | ローカル LLM | latest |
| FastAPI | vulnerable app | latest |
| JupyterLab | notebook | 4+ |
| `llm-client` (path dep) | LLM 呼出 wrap | (monorepo) |
| DeepTeam | red team (主軸) | latest pinned |
| PyRIT | red team (multi-turn) | latest pinned |
| Snyk CLI | LLM03 静的解析 | latest |
| gitleaks | LLM03 静的解析 | latest |

### 5.4 Non-Functional Requirements

#### 性能 (Performance)
- 各章単発実行 (`make attack-01`): 5 分以内
- `make eval-all` 全 10 章: 60 分以内 (Ollama mistral 想定)
- Vertex 切替時の latency: API 経由のため Ollama より 2〜3 倍速い

#### コスト (Cost)
- Ollama 既定: **¥0**
- Vertex Claude 切替時: `make eval-all RUNTIME=vertex` 1 回で ~¥100、月次運用で ~¥500
- ストレージ: Ollama モデル 3 種で ~15GB

#### プライバシー / データ保持
- 学習教材なので PII を扱わない (テストプロンプトは公開ベンチマーク or 自作の合成データのみ)
- `results/` JSON は git commit 対象外 (`.gitignore` で除外)
- LINE userId 等の PII を含む `analytics-platform` への emit はしない (本ラボは emit 自体しない)

#### キャパシティ
- 個人ローカル実行が主、同時利用想定なし
- disk: Ollama 3 モデル ~15GB + Docker image 数 GB = 計 20〜25GB
- memory: Ollama mistral 推論で 8GB、llama-guard 同時実行で +8GB = 16GB 推奨

---

## 6. Drawbacks

- **保守コスト**: OWASP LLM Top 10 は年次改訂、DeepTeam / PyRIT も活発に更新。半年〜1 年に 1 度の全章 review が必要
- **`security-platform` との重複コード**: 同じ防御ロジック (rate limit / input filter) を別実装。production との drift リスクはあるが、学習教材としての readability を優先するトレードオフ
- **「教材 = ベストプラクティス」と誤解されるリスク**: 各 README で「これは toy 実装、production は別」を明示する必要
- **disk 圧迫**: Ollama 3 モデルで 15GB、CI 環境では mock LLM での smoke test に限定する必要
- **個人運営で全 10 章を維持する負担**: Phase 単位で進めても 10 PR、トータル 12〜15 週相当。途中で陳腐化する章が出る可能性
- **OSS 公開しない判断のもったいなさ**: 教材として完成度を高めても公開しないので外部からの貢献は受けられない

## 7. Alternatives

### 案 A: OWASP `www-project-promptme` をフォークして monorepo に取り込む
- 概要: 既存 OSS をベースにし、monorepo 規約 (FastAPI / uv) に合わせて改修
- 却下理由: (1) Flask → FastAPI、Python 3.10 → 3.12、pip → uv の改修コストは独自実装と大差ない、(2) promptme のチャレンジは Flask の HTML UI 前提で、本ラボの「notebook 中心」とは UX が違う、(3) ライセンス・upstream merge の運用負荷

### 案 B: `security-platform` の中に教材を組み込む
- 概要: 別ディレクトリではなく `security-platform/learning/` 配下に置く
- 却下理由: (1) `security-platform` は production 防御層であり、教材を混ぜると責務が曖昧、(2) 教材用の Ollama / JupyterLab 依存を production システムに持ち込むのは過剰、(3) PROPOSAL-0002 (Promptfoo → DeepTeam) との進行が絡む

### 案 C: notebook だけで完結、vulnerable app を立てない
- 概要: FastAPI app を作らず、notebook 内で LLM 直接呼出 → 攻撃 → 防御を 1 cell 内で実演
- 却下理由: (1) 「web app の API として晒される LLM」が現実の脅威モデル、notebook 内では再現しきれない、(2) 防御の差し替え (`DEFENSE_VERSION` env) のような production 的な切替が体験できない、(3) Docker 統合の利点 (Ollama / Llama Guard の連携) が活きない

### 案 D: 10 章を一度に全部実装
- 概要: Phase 分割せず大 PR 1 本で全章
- 却下理由: (1) レビュー不可能、(2) 12〜15 週の作業を一括 commit はリスク高、(3) Phase 0 (共通基盤) の設計を各章実装フィードバックで改善する機会が失われる

### 案 E: DeepTeam ではなく Promptfoo を使う
- 概要: 既存 `security-platform/.promptfoo/redteam.yaml` を流用、Node.js 依存を許容
- 却下理由: (1) Python ベースの monorepo に Node.js 依存を増やす、(2) PROPOSAL-0002 で DeepTeam 移行が決まれば結局 rewriting、(3) Python ネイティブの方が notebook 統合が clean

### 案 F: ローカル LLM (Ollama) ではなく Vertex AI Claude を既定にする
- 概要: ローカルモデル不要、API key だけで動く
- 却下理由: (1) 月額コストが学習者に発生、(2) 「ローカル完結 = 安全に試せる」というラボの設計思想と矛盾、(3) Vertex の rate limit に学習者が引っかかる懸念

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-24 | Draft | 初稿 (Claude Code との設計セッション経由) |
