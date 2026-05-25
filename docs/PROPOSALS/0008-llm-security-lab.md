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

OWASP LLM Top 10 (2025) の 10 種類の脆弱性について、**「攻撃を体感し、防御の効果を定量的に測る」** ハンズオン教材を monorepo 内 `llm-security-lab/` に整備する。各脆弱性で **意図的に脆弱な FastAPI アプリ (v0=防御なし baseline) + 攻撃シナリオ + 段階的防御 (v1〜v3) + Jupyter notebook** を提供し、`make attack-01 / make defend-01` 形式で学習者がローカルで完結して体験できる構成にする。

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

- [ ] OWASP LLM Top 10 (2025) 全 10 項目それぞれに「vulnerable app (v0 baseline) + attack + defense (v1〜v3) + notebook」を整備
- [ ] 各章で **攻撃成功率の段階的低下** が定量化される (例: v0 80% → v1 60% → v2 25% → v3 5%)
- [ ] 学習者が `git clone` + `docker compose up` + `jupyter lab` で 5 分以内に動かせる
- [ ] **LLM ランタイムは Ollama 既定でクラウドコストゼロ** (Vertex 切替は optional)
- [ ] 各章の README で **攻撃概要 / 攻撃方法 / 防御策** を OWASP 公式定義 + 実例 + 自分の言葉で記述
- [ ] DeepTeam の YAML / PyRIT の Python script として **再利用可能な攻撃資産** を蓄積
- [ ] 各章で実証された防御の **production agent への持ち込み判断**: §3.10 で定義する客観基準 (攻撃成功率改善 ≥ 50pp、 false positive < 5%、 latency overhead < +500ms 等) を満たした章は **章 × agent ごとに 1 proposal** で起票 (例: paper-qa への LLM01 持ち込み)、 `security-platform` 集約は別 proposal

### 2.2 Non-Goals

- **production への直接導入**: `llm-security-lab/` は学習教材であり、`security-platform` のような production 防御層は別物。将来の持ち込みは別 proposal で
- **`security-platform` への直接依存**: 意図的にコード重複を許容し、独立して動く構成にする。学習材料としての readability 優先
- **独立 OSS リポジトリとしての切り出し / 宣伝**: 本 monorepo (`sakamoto-family-smile/agent_monorepo`) は **public repo** のため、 ここに置く時点で実質 OSS として公開される。 ただし `llm-security-lab/` を独立 repo に切り出して promote する (例: `awesome-llm-security` への登録 / blog post / OWASP コミュニティ寄稿) のは Phase 11 以降の検討事項とし、 Phase 1-10 中は monorepo 内に閉じて完成度を高めることに集中する
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

| ツール / データソース | 担当章 | 理由 |
|---|---|---|
| **DeepTeam** | 01, 02, 05, 06, 09, 10 (主軸) | Python ネイティブ、OWASP マッピング公式、PROPOSAL-0002 とも整合 |
| **PyRIT** | 01 (Crescendo), 07 (System Prompt Leakage 多段抽出) | Multi-turn 攻撃が本家、「複数ターンで段階的に jailbreak する怖さ」を体感させる |
| **PoisonedRAG dataset** (NeurIPS 2024) + adapter script | 04 (RAG poisoning) | 公開 dataset で再現性を確保 (自前 corpus 生成より検証可能性が高い)。 adapter は本ラボの vulnerable app の RAG store に poison サンプルを差し込む薄い wrapper |
| **vec2text (NeurIPS 2023 公式実装) + RAG-Truth サンプル** | 08 (Vector Weakness: embedding inversion) | 公開モデル / dataset を使い、 「埋め込みから原文を復元できる」 ことを学習者が再現可能。 自前実装は脱落 |
| **Giskard (補助)** | 05 (Output Handling), 09 (Misinformation) で評価部分 | scanner として output schema / hallucination 検出を組み合わせ評価 (§7 案 H 参照、 補助利用) |
| **Inspect AI (補助)** | 09 (Misinformation) で TruthfulQA タスク定義 | UK AISI の評価フレームワーク、 task 定義を本ラボの notebook から呼ぶ (§7 案 I 参照、 補助利用) |
| **静的解析 (Snyk / gitleaks)** | 03 (Supply Chain) | red team ツールの対象外領域 |

### 3.6 LLM ランタイム

| ランタイム | 既定 / optional | モデル例 | 用途 |
|---|---|---|---|
| **Ollama** | 既定 | mistral / llama3 / sqlcoder / granite | 全章のローカル実行 |
| **Vertex AI Claude** | optional | claude-haiku-4-5 / claude-sonnet-4-6 | 比較学習用 (`LLM_RUNTIME=vertex` で切替) |
| **`llm-client` (path dep)** | 内部 wrap | (両者を抽象化) | monorepo 規約準拠 |

「OSS LLM では効く攻撃が Claude には効かないか？」を体感できる構成。

### 3.7 Phase ロードマップ (PR 分割)

レビューしやすさを優先して **PR は小粒**に保つ (PROPOSAL-0006 EDINET 統合 / PROPOSAL-0007 paper-qa-agent と同じ細分化方針)。

| Phase | PR | 内容 | 工数目安 |
|---|---|---|---|
| **Phase 0a** | PR-A1 | ディレクトリ骨格 + `pyproject.toml` (uv workspace) + `docker-compose.yml` 雛形 + `Makefile` 雛形 + ルート `README.md` | 半日〜1日 |
| **Phase 0b** | PR-A2 | `shared/llm_runtime/` (Ollama + Vertex + `LLM_RUNTIME` 切替) + `llm-client` 統合 | 半日〜1日 |
| **Phase 0c** | PR-A3 | `shared/attacks/` (DeepTeam runner + PyRIT runner) + `shared/defenses/` 雛形 + `shared/eval/` (attack_success_rate + reporter) | 1〜2日 |
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
| **Phase 11** | PR-X | (optional) §3.10 の基準を満たした章を **章 × agent ごとに 1 proposal** で持ち込み起票 (例: paper-qa への LLM01)、 横断防御は `security-platform` 集約 proposal | — |

各章 Phase 1-10 は Phase 0c 完了後 **任意の順序で並行進行可能**。 推奨順は **production agent への影響度順** で:

```
Phase 1 (Prompt Injection) → Phase 2 (Sensitive Info) → Phase 7 (System Prompt Leakage)
  → Phase 6 (Excessive Agency) → Phase 10 (Unbounded Consumption)
  → Phase 5 (Output Handling) → Phase 9 (Misinformation) → Phase 4 (Poisoning)
  → Phase 8 (Vector Weakness) → Phase 3 (Supply Chain)
```

理由: LLM01/02 は monorepo 全エージェント (LINE Bot 系) の即時リスク、 LLM07 は paper-qa-agent / driving-license-bot の System Prompt 設計に直結、 LLM06/10 は agent SDK + Cloud Run の運用設計に直結する順序。 LLM03 は静的解析中心で他章と独立なので最後でも問題なし。

### 3.8 Notes / Constraints / Caveats

- **PROPOSAL-0002 (Promptfoo → DeepTeam 移行) との関係**: 0002 は `security-platform` の red team を Promptfoo から DeepTeam に置き換える提案で、 現時点では Draft。 本 proposal (0008) は **0002 の status に依存しない**。 むしろ Phase 0c で DeepTeam runner を本ラボ側で先行検証することで、 0002 の Implementing 着手前に DeepTeam の使い勝手 / 制約 / 統合パターンを実証できる ⇒ 0008 → 0002 の順で進めるのが安全。 DeepTeam の API / version pinning は本ラボの `uv.lock` を 0002 で参照すれば drift を抑えられる
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
| **本ラボの攻撃 runner から誤って production endpoint を叩く** | High | (1) `shared/attacks/_target_guard.py` で attack target を `localhost` / `vulnerable-app-*` Docker service 名のみ allowlist、 production の `cloud-run.app` 等のドメインは ValueError で reject。 (2) `LAB_ALLOW_EXTERNAL_TARGET=true` を明示的に立てない限り外部接続不可。 (3) DeepTeam / PyRIT runner にも同じ guard を通す |
| **JupyterLab token が弱い (`localdev`)** | Medium | (1) docker-compose の jupyter port を `127.0.0.1:8888:8888` で host 側 localhost にバインド (外部 expose しない)。 (2) `.env.example` に `JUPYTER_TOKEN` を 32 文字以上のランダム値で生成する手順記載。 (3) `JUPYTER_TOKEN=localdev` 残置時に起動ログで警告を出す |
| Ollama モデル容量で disk 圧迫 | Low | mistral (4GB) / llama3 (4.7GB) / llama-guard (4.7GB) の合計 ~15GB。README に明記、`make clean-models` 用意 |
| `security-platform` との重複コードが drift する | Medium | コードは drift して OK (学習用なので)。**設計の drift は Phase 11 で別 proposal で吸収** |
| 月額コストが見えにくい | Low | `make eval-all RUNTIME=vertex` 実行前にコスト見積もりを表示 |

### 3.10 production agent への持ち込み判断基準

本ラボの各章で実証された防御は、 monorepo の他エージェント (paper-qa / driving-license / stock-analysis / fujisawa-info / lifeplanner / piyolog 等) や `security-platform` への持ち込みを検討する。 「持ち込む / 持ち込まない」 を **客観基準** で判断するため、 章ごとに以下を測る。

#### 3.10.1 採用判定基準 (持ち込み判断のチェックリスト)

| 基準 | 閾値 | 測定方法 |
|---|---|---|
| **防御効果**: v0 → v3 (or 最も良い defense version) の攻撃成功率改善 | **≥ 50pp 低減** (例: 80% → 30%) | `make eval-all` の `results/<chapter>/v3.json` で算出 |
| **false positive**: 防御による正常リクエスト阻害率 | **< 5%** | 各章 `tests/test_defenses.py` に正常 prompt 100 件の suite 必置 |
| **latency overhead**: defense version 適用時の p95 increase | **< +500ms** | shared/eval/reporter.py で latency を測定 |
| **monorepo 統合性**: `llm-client` / `analytics-platform` / `security-platform` の既存 API で完結 | 必須 | 防御コードのレビュー時に確認 |
| **運用 cost**: token / disk / 外部 API 課金 | agent 別 budget 内 | 各 agent の per-system cost 表で確認 |
| **再現性**: regression mode (§4.6) で ±5% 以内 | 必須 | `make eval-NN VER=v3 SEED=42 TEMPERATURE=0` |

5/6 以上を満たせば持ち込み推奨、 3-4 個なら個別判断、 2 個以下なら持ち込まず本ラボ内で参考実装に留める。

#### 3.10.2 章 × production agent 想定マッピング

各章を最初に持ち込む候補 (Phase 11 別 proposal で個別検証):

| 章 | OWASP | 主な持ち込み候補 agent | 理由 |
|---|---|---|---|
| 01 | Prompt Injection | **全 LINE Bot 系** (paper-qa, driving-license, fujisawa-info, fujisawa-hokatsu, lifeplanner, piyolog) | LINE webhook = ユーザ入力経路で全エージェント該当 |
| 02 | Sensitive Info Disclosure | **paper-qa, lifeplanner, piyolog** | PII (会話履歴 / 家族情報 / 子情報) を扱う agent |
| 03 | Supply Chain | **monorepo 全体** (cross-agent) | dependency pinning / SBOM は monorepo 横断で運用、 個別 agent ではなく root CI に組み込む |
| 04 | Data and Model Poisoning | **paper-qa, fujisawa-info-bot** | RAG (pgvector) を使う agent。 corpus 整合性 hash と参照元 trust score を入れる |
| 05 | Improper Output Handling | **全 agent** | LLM output を user に返す手前で schema validation / HTML sanitize |
| 06 | Excessive Agency | **driving-license-bot, stock-analysis-agent, paper-qa-agent** | Tool calling + Claude Agent SDK を使う agent。 tool whitelisting + approval gate |
| 07 | System Prompt Leakage | **paper-qa, driving-license-bot** | System prompt に専門ドメイン知識 / 振る舞いルールを含む agent、 漏洩で意図された制限が外れるリスク |
| 08 | Vector Weakness | **paper-qa, fujisawa-info-bot** | pgvector 利用、 embedding signing と provenance check |
| 09 | Misinformation | **driving-license-bot, fujisawa-info-bot, fujisawa-hokatsu-agent** | 法令 / 制度 / 公的情報を返す agent。 CoVe + retrieval 必須化 |
| 10 | Unbounded Consumption | **全 production agent** | rate limit / token budget / max iterations は LINE Bot 共通要件 |

#### 3.10.3 持ち込み proposal の起票単位

「全 10 章まとめて 1 proposal」 ではなく、 **章 × agent ごとに 1 proposal**を起票 (例: `PROPOSAL-NNNN: paper-qa-agent への LLM01 Prompt Injection 対策持ち込み`)。 これにより各持ち込みの可否を独立に judge でき、 持ち込みコストの妥当性を agent オーナーが判断しやすくなる。

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
    - 攻撃成功率の数値が再現すること:
        - **regression mode** (`seed` 固定 + `temperature=0`): **±5%** 以内 (CI 回帰テストの判定基準)
        - **stochastic mode** (production 想定の温度設定): **±20%** 以内、 3 回試行の中央値 (体感用)
    - regression mode で v1 と v2 の数値差 (例: 60% → 25%) が tolerance を超えて重なる場合は防御設計を見直す

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
- **独立 OSS リポジトリ化を後回しにする**: 本 monorepo は public なので置いた時点で実質公開 OSS だが、 `llm-security-lab/` を独立 repo に切り出して外部から見つけてもらう動線 (README badge / OWASP 紹介 / blog 等) は Phase 11 以降。 その間は 「探されない OSS」 状態で外部貢献を受けにくい状態が続く

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

### 案 G: Garak (NVIDIA) を主軸採用 (DeepTeam の代替)
- 概要: NVIDIA 製の LLM vulnerability scanner `garak`。 OWASP LLM Top 10 (2025) マッピングが公式ドキュメントに整備され、 probe 種類数は DeepTeam を上回る。 active development + NVIDIA backing
- 却下理由:
  - (1) **CLI-first で Python API は薄い**: notebook 統合では `subprocess.run(["garak", ...])` 越しになり、 attack 結果の dataclass / Pydantic 化が困難。 本ラボの `shared/eval/AttackResult` 抽象が活きない
  - (2) **multi-turn 攻撃が弱い**: Garak は single-turn probe が中心で、 LLM07 (System Prompt Leakage) で必要な Crescendo 攻撃には PyRIT 併用が結局必要
  - (3) **カスタム probe 拡張が DeepTeam より複雑**: probe を Python class で書く規約が proprietary、 monorepo の `llm-client` との統合に boilerplate が増える
  - (4) **PROPOSAL-0002 (DeepTeam 移行) との二重採用回避**: 本ラボで Garak、 production で DeepTeam とすると monorepo 内に 2 種の red team フレームワークが並存し設計判断の根拠が分散する
- ただし将来 OWASP 公式 conformance テストが Garak に偏った場合は再評価対象とする

### 案 H: Giskard を主軸採用
- 概要: ML / LLM の compliance / quality scanner。 RAG eval が強い、 LLM evaluation harness としての完成度高い
- 却下理由:
  - (1) **red team ツールではなく LLM scanner**: 攻撃シナリオ実行ではなく LLM 品質 / compliance 評価が主目的、 「攻撃を体感する」 本ラボのコンセプトと方向性がずれる
  - (2) **OWASP マッピング非対応**: OWASP LLM Top 10 (2025) との対応が公式ドキュメント上で取られていない。 本ラボの §3.4 マッピングが Giskard 機能だけでは埋まらない
  - (3) **multi-turn 不対応**: LLM01 Crescendo / LLM07 多段抽出が実演できない
- LLM09 (Misinformation) / LLM05 (Improper Output Handling) の評価部分だけ Giskard を補助的に利用するのは選択肢。 §3.5 ツール選定で 「補助利用」 として再考の余地は残す

### 案 I: Inspect AI (UK AISI) を主軸採用
- 概要: 英国 AI Safety Institute 製の評価フレームワーク。 reproducibility と eval harness の完成度が高い
- 却下理由:
  - (1) **red team specific ではなく一般 LLM eval フレームワーク**: TruthfulQA / MMLU 等の評価向けで、 OWASP LLM Top 10 攻撃シナリオの probe ライブラリが付属しない
  - (2) **OWASP マッピング欠落**: 案 H と同じ理由
  - (3) **学習教材として overhead**: eval task の定義が agency-flavor (英国 AISI 公式評価向け) で個人学習用途には抽象度が高すぎる
- ただし LLM09 (Misinformation) で TruthfulQA を回す部分は Inspect AI の task 定義が活用できる可能性あり (§3.5 で補助検討)

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-24 | Draft | 初稿 (Claude Code との設計セッション経由) |
