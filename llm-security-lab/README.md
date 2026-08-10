# llm-security-lab

OWASP LLM Top 10 (2025) 体験学習ラボ。 各脆弱性で **「攻撃を体感し、 防御の効果を定量的に測る」** ハンズオン教材を提供する。

> 設計の根拠: [`docs/PROPOSALS/0008-llm-security-lab.md`](../docs/PROPOSALS/0008-llm-security-lab.md) を参照。

## ⚠️ 重要な注意

- 本ラボの攻撃 runner は **個人のローカル環境での学習目的のみ** で使うこと。 他者システム / 本 monorepo の production endpoint への無断試行は **禁止**。
- 攻撃 target は Phase 0c 以降 `localhost` / Docker service 名のみ allowlist される。 外部 endpoint を試行する場合は `LAB_ALLOW_EXTERNAL_TARGET=true` を明示的に立てる必要がある (それでも自分が所有 / 許可された target のみに限定すること)。
- JupyterLab port は host 側で `127.0.0.1:8888` にのみバインドされる (外部 expose 防止)。 `JUPYTER_TOKEN` は `.env` で 32 文字以上のランダム値に上書きすること (デフォルト `localdev` は起動時に警告)。

## 構成 (Phase 0a 時点)

```
llm-security-lab/
├── README.md             ← 本ファイル (OWASP マッピング + 学習順序)
├── CONVENTIONS.md        ← 各章のファイル構成・命名規約・notebook の書き方
├── pyproject.toml        ← uv workspace, Phase 0b/0c で path dep / extras 追加
├── docker-compose.yml    ← Ollama + JupyterLab (Phase 1+ で vulnerable-app-NN を profile 追加)
├── Makefile              ← setup-base / jupyter / clean 等
├── .env.example          ← 環境変数雛形 (`cp .env.example .env` → 編集)
├── shared/               ← Phase 0b/0c で実装
│   └── Dockerfile.jupyter
├── notebooks/            ← JupyterLab 起点 (Phase 0b/0c で 00_index.ipynb 追加)
└── tests/                ← Phase 0c 以降
```

Phase 1 以降で各章ディレクトリ (`01_prompt_injection/` 〜 `10_unbounded_consumption/`) が追加される。

## クイックスタート (Phase 0a)

```bash
# 環境変数を準備
cp .env.example .env
# .env を編集し、 JUPYTER_TOKEN を 32 文字以上のランダム値に変える
# (例: python -c "import secrets; print(secrets.token_urlsafe(32))")

# JupyterLab + Ollama を起動
make setup-base

# (初回のみ、 ローカル LLM モデルを pull、 disk 約 15GB 消費)
make setup-models

# JupyterLab を foreground で起動 → http://127.0.0.1:8888 にアクセス
make jupyter
```

Phase 0b 以降の学習体験 (`make attack-NN` / `make defend-NN` / notebook) は順次追加される。

## OWASP LLM Top 10 (2025) × 章マッピング

| 章 | OWASP # | 名前 | 主な攻撃ツール | 主な防御アプローチ | Phase |
|---|---|---|---|---|---|
| 01 | LLM01 | Prompt Injection | DeepTeam + PyRIT (Crescendo) | system prompt hardening / Llama Guard / input filter / 多層 | Phase 1 |
| 02 | LLM02 | Sensitive Information Disclosure | DeepTeam | output redaction / PII scrubber / log sanitization | Phase 2 |
| 03 | LLM03 | Supply Chain | 静的解析 (Snyk, gitleaks) | 依存 pinning / SBOM / MCP server hash | Phase 3 |
| 04 | LLM04 | Data and Model Poisoning | PoisonedRAG dataset + adapter | corpus hash / 参照元 trust score / freshness check | Phase 4 |
| 05 | LLM05 | Improper Output Handling | DeepTeam / Giskard 補助 | output schema validation / HTML sanitize / URL allowlist | Phase 5 |
| 06 | LLM06 | Excessive Agency | DeepTeam (agentic tool abuse) | tool whitelisting / scope minimization / approval gate | Phase 6 |
| 07 | LLM07 | System Prompt Leakage | PyRIT (多段抽出) | prompt isolation / secret 別管理 / detection rule | Phase 7 |
| 08 | LLM08 | Vector and Embedding Weaknesses | vec2text + RAG-Truth | provenance check / embedding signing / outlier 検出 | Phase 8 |
| 09 | LLM09 | Misinformation | Inspect AI (TruthfulQA) + Giskard 補助 | Chain-of-Verification / retrieval 必須化 / confidence threshold | Phase 9 |
| 10 | LLM10 | Unbounded Consumption | 無限 prompt / loop / 巨大 context | rate limit / token budget / max iterations / circuit breaker | Phase 10 |

## 推奨学習順序

各章は Phase 0c 完了後は独立に進められるが、 **production agent への影響度順** で以下を推奨:

```
Phase 1 (Prompt Injection) → Phase 2 (Sensitive Info) → Phase 7 (System Prompt Leakage)
  → Phase 6 (Excessive Agency) → Phase 10 (Unbounded Consumption)
  → Phase 5 (Output Handling) → Phase 9 (Misinformation) → Phase 4 (Poisoning)
  → Phase 8 (Vector Weakness) → Phase 3 (Supply Chain)
```

理由: LLM01/02 は monorepo 全 LINE Bot 系の即時リスク、 LLM07 は System Prompt 設計に直結、 LLM06/10 は agent SDK + Cloud Run の運用設計に直結。 LLM03 (静的解析中心) は独立に進められるため最後。

## production agent への持ち込み判断

各章で実証された防御の本 monorepo 各 agent への持ち込みは、 proposal 0008 §3.10 で定義する客観基準 (攻撃成功率改善 ≥ 50pp、 false positive < 5%、 latency overhead < +500ms 等) で判断する。 章 × agent ごとに 1 proposal で起票する想定。

## 参考

- OWASP LLM Top 10 (2025): <https://genai.owasp.org/llm-top-10/>
- DeepTeam: <https://github.com/confident-ai/deepteam>
- PyRIT: <https://github.com/Azure/PyRIT>
- Ollama: <https://ollama.com/>
- monorepo `security-platform/`: production 用横断防御層 (本ラボとは独立)
