# PROPOSAL-0002: security-platform の red team を Promptfoo から DeepTeam に置き換え

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-09 |
| **Updated** | 2026-05-09 |
| **Target** | security-platform |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

security-platform の red teaming 実装を **Promptfoo (Node.js CLI、`scripts/redteam.sh`)** から
**DeepTeam (Python ライブラリ)** に置き換える。これにより red team を独立した artifact 生成
job から、`analyzer/` パイプラインに編み込まれた **CI gating 可能な Python テスト** に変える。

副次的に Node.js 18+ の前提が `scan-mcp.sh` / `scan-skills.sh` (uvx + Snyk MCP scan) のみに
縮退し、red team 経路では消える。Phase 5+ の Cloud デプロイ時の image サイズも下げられる。

## 2. Motivation

### 現状の課題

1. **Red team 結果がパイプラインから孤立**:
   - `scripts/redteam.sh` は `npx promptfoo` を呼び出して `logs/redteam-*.json` を吐くだけ
   - SQLite (`scan_results` / `audit_logs`) と無関係、Dashboard (`:8000`) に出ない
   - 失敗を Slack / LINE に通知するパスが無い (analyzer 用 notifier と非接続)
2. **CI gating 不能**: `redteam.sh` は run-and-forget。assertion 失敗で merge を止める仕組みが無い
3. **Node.js 依存**: security-platform の他コンポーネント (collector / analyzer / proxy / dashboard)
   は全て Python。red team のためだけに Node.js 18+ を要求している
4. **DLP / proxy との統合検証が出来ない**: `proxy/dlp.py` は Python 関数として存在するが、
   Promptfoo (別プロセス) からは呼べないため「LLM が PII を吐く + DLP で止められる」という
   defense-in-depth を 1 テストで検証できない

### 放置するとどうなるか

- red team は手動実行のままになり、Phase 4 (CI gating) の延長線で 3 番目の merge gate にできない
- DESIGN.md の F12-F18 (proxy 防御層) が red team 経路で実証されず、retrospective な
  「あの defense は本当に効いていたか？」の根拠が薄い
- 各 agent (kanie-lab / driving-license-bot 等) を red team 対象に広げる際、
  YAML config を増やすたびに Promptfoo plugin の挙動を読み込む必要があり onboarding 摩擦が残る

### 2.1 Goals

- [ ] `scripts/redteam.sh` を `pytest tests/redteam/` に置換し、CI で実行可能にする
- [ ] DeepTeam の `red_team()` を `analyzer/` 共有 LLM client (Anthropic / Vertex Gemini) で動かす
- [ ] 結果を SQLite `scan_results` テーブルに persist し、Dashboard / notifier から再利用可能にする
- [ ] `pr-tests.yml` または `pr-security.yml` に red team job を追加 (gating は段階的に有効化)
- [ ] Promptfoo の MCP 特化テストに相当する coverage を **DeepTeam の custom Vulnerability** で再現
- [ ] Node.js 18+ を red team 経路から外す (README §0.1 prerequisites を更新)

### 2.2 Non-Goals

- DeepTeam を **eval framework** としても全面採用すること (eval ニーズが顕在化するまで保留)
- Confident AI Cloud (有料 SaaS) との連携 (OSS 範囲のみで完結させる)
- 各 agent の red team を本 PR で実施すること (security-platform 内の sample target で検証、
  各 agent への展開は別 PR / 別 proposal で扱う)
- Promptfoo を完全削除すること (後述: 短期的には `redteam-legacy.sh` として残す)
- security-platform 以外の eval 用途への DeepTeam 採用 (lifeplanner / piyolog 等は対象外)

---

## 3. Proposal

### 3.1 アプローチ概要

Promptfoo を **完全置換** する。並走 (DeepTeam 主軸 + Promptfoo を MCP 特化のみ残す) も検討したが、
2 系統メンテのコストを払うほど Promptfoo の MCP plugin が unique かは怪しく、custom Vulnerability
1 個書けば代替できる見込みのため、シンプルな置換を選ぶ。

ただし**急に外すリスク**を避け、段階的に切替:
- **Phase A (本提案 1 回目 PR)**: DeepTeam を pyproject.toml に追加 + `tests/redteam/` 雛形 + `scripts/redteam.sh` は残す
- **Phase B (2 回目 PR)**: 既存 14 plugins 相当の DeepTeam 版を実装 + MCP custom Vulnerability 実装
- **Phase C (3 回目 PR)**: CI に red team job を追加 (`continue-on-error: true` で 1〜2 週間観察)
- **Phase D (4 回目 PR)**: gating 有効化 + `scripts/redteam.sh` を `redteam-legacy.sh` にリネーム (1 release 後に削除予定)
- **Phase E (5 回目 PR)**: `.promptfoo/` ディレクトリ + `redteam-legacy.sh` 削除、`promptfoo` Node.js 依存記述を README から除去

### 3.1 User Stories

#### 3.1.1 ストーリー 1: PR 内で red team が回る

> 開発者が `proxy/dlp.py` の regex パターンを変更する PR を出すと、`pr-security.yml` の
> red team job が `PIILeakage` カテゴリで現状の DLP が leakage を防げているかをテストし、
> regression を起こした場合は merge を blocking する。失敗内容は SARIF 風の JSON で artifact に残り、
> Dashboard でも `scan_results` テーブル経由で表示される。

#### 3.1.2 ストーリー 2: MCP 攻撃を新規エージェントに対して回す

> 新しいエージェント (例: lifeplanner-agent) が MCP server を使い始めた時、
> security-platform 側で `tests/redteam/test_lifeplanner.py` を 1 ファイル追加するだけで
> 該当 agent の MCP tool 呼出に対して `MCPToolResultInjection` (custom Vulnerability) と
> `RBAC` / `BOLA` を回せる。inventory.yaml 登録と並列のフロー。

### 3.2 Notes / Constraints / Caveats

- DeepTeam は急速に進化中のため、**特定 minor version に pin** する (`deepteam>=0.x.y,<0.x+1`)。
  attack/vulnerability の rename を CI 失敗で気付ける状態を維持
- Confident AI Cloud (`deepeval login`) は **使わない**。`deepteam` の OSS 範囲のみ
- DeepTeam の simulator/evaluator model 呼出は LLM コストが発生するため、CI では **smoke 規模 (各 vulnerability 1 test)** に留め、full run (各 5+ test) は cron / 手動トリガに限定
- `analyzer/llm_analyst.py` の Anthropic / Vertex Gemini クライアントを `BaseLLM` でラップして simulator/evaluator として再利用 (LLM 接続を一箇所に集約)
- DeepTeam の vulnerability `Misuse` 配下の `IllegalActivity` / `GraphicContent` は monorepo の用途と離れているため **採用しない** (家族向け agent / 個人 LLM 用途には過剰)

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| DeepTeam の API 変更で CI が壊れる | Medium | minor version pin + Renovate / dependabot で PR 化、changelog 確認をルーチン化 |
| MCP custom Vulnerability の質が Promptfoo `mcp` plugin より劣る | High | Phase B の PR で Promptfoo の `mcp` plugin の test corpus を読み、再現する attack template を 5 シナリオ以上書く。Promptfoo の `redteam-latest.json` を baseline として保存 |
| LLM 呼出コスト増加 (simulator + evaluator で 2 倍) | Medium | CI は smoke (各 1 test) に絞る、Haiku / Gemini Flash を simulator/evaluator に使う、月次予算を §5.4 で明記 |
| Confident AI Cloud に意図せず送信 | Low | `DEEPEVAL_TELEMETRY_OPT_OUT=YES` + `CONFIDENT_API_KEY` 未設定で local-only 動作確認、CI workflow に env を明示 |
| Node.js 削除で `scan-mcp.sh` / `scan-skills.sh` の Snyk MCP scan も影響 | Low | red team 経路と独立。README prerequisites では「red team は不要、scan-mcp/skills は引き続き必要」と明記 |
| 既存の `logs/redteam-*.json` baseline 喪失 | Low | 過去 run を `logs/legacy/promptfoo/` に移し、最後の run を Phase B PR の review 材料として残す |
| DeepTeam の vulnerability classes が monorepo の用途と乖離 (Bias / Toxicity 等) | Low | §3.2 の通り採用 vulnerability を絞り込む。security-platform は OWASP ASI / LLM Top 10 のうち agent / MCP 関連を主軸 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

**現状 (Promptfoo)**:

```
scripts/redteam.sh
   │
   ▼
npx promptfoo@latest redteam run --config .promptfoo/redteam.yaml
   │
   ▼
logs/redteam-{timestamp}.json   ← 結果は孤立、再利用なし
logs/redteam-latest.html
```

**移行後 (DeepTeam)**:

```
pytest tests/redteam/
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ tests/redteam/                                                │
│   conftest.py        ← target_callback / simulator / eval LLM │
│   test_general.py    ← 既存 14 plugins 相当の vulnerability   │
│   test_mcp.py        ← MCP custom vulnerability (新規)        │
│   test_dlp.py        ← proxy/dlp.py との統合テスト (新規)     │
└──────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ src/redteam/  (新規モジュール)                                  │
│   models.py         ← BaseLLM で analyzer/llm_analyst を wrap │
│   vulnerabilities/  ← MCP / DLP / cross-session 等の custom    │
│   reporter.py       ← RiskAssessment → scan_results に persist │
└──────────────────────────────────────────────────────────────┘
   │
   ▼
SQLite scan_results テーブル (scan_type='redteam')
   │
   ├──▶ Dashboard `:8000` で表示
   └──▶ Notifier (Slack / LINE) で重大度に応じて通知
```

### 4.2 データモデル

新規テーブルなし。**既存 `scan_results` テーブルを再利用**:

```python
class ScanResult(Base):
    __tablename__ = "scan_results"
    id: int
    scan_type: str         # 'gitleaks' / 'mcp_scan' / 'redteam' (新規 enum 値)
    target_path: str       # 'security-platform' / agent name
    findings: dict         # JSON: { vulnerability_name, attack_method, score, breached_inputs }
    ran_at: datetime
```

`findings` JSON の schema (DeepTeam の `RiskAssessment` を pure dict に変換):

```json
{
  "summary": {
    "total_tests": 25,
    "passed": 23,
    "failed": 2,
    "pass_rate": 0.92
  },
  "vulnerabilities": [
    {
      "name": "PIILeakage",
      "owasp_category": "LLM06",
      "tests": [
        {
          "attack_method": "Crescendo",
          "input": "...",
          "output": "...",
          "score": 0.0,
          "passed": false,
          "reason": "Output contains email-like pattern"
        }
      ]
    }
  ],
  "metadata": {
    "deepteam_version": "0.x.y",
    "target_model": "claude-haiku-4-5",
    "simulator_model": "claude-haiku-4-5",
    "evaluator_model": "claude-haiku-4-5",
    "ran_at": "2026-05-09T12:00:00Z"
  }
}
```

### 4.3 API

新規 HTTP API なし。Dashboard 側に red team 結果表示の view を追加するのみ:

| 変更 | 場所 |
|---|---|
| `/scan-results?type=redteam` route 追加 | `src/dashboard/app.py` |
| Jinja template `redteam_results.html` 追加 | `src/dashboard/templates/` |
| Sidebar nav に「Red Team」リンク追加 | 既存 base template |

### 4.4 主要モジュール

新規追加:

```
security-platform/
├── src/
│   └── redteam/                    (新規パッケージ)
│       ├── __init__.py
│       ├── models.py               ← AnalystLLM (BaseLLM 実装)
│       ├── runner.py               ← run_redteam() のエントリポイント
│       ├── reporter.py             ← RiskAssessment → scan_results 保存
│       └── vulnerabilities/
│           ├── __init__.py
│           ├── mcp_tool_injection.py   ← Promptfoo `mcp` plugin の代替
│           ├── memory_poisoning.py     ← Promptfoo `agentic:memory-poisoning` 代替
│           ├── cross_session_leak.py   ← Promptfoo `cross-session-leak` 代替
│           └── ascii_smuggling.py      ← Promptfoo `ascii-smuggling` 代替
├── tests/
│   └── redteam/                    (新規)
│       ├── __init__.py
│       ├── conftest.py             ← fixtures (target_callback / models)
│       ├── test_general.py         ← OWASP 主要カテゴリ (DeepTeam 標準 vulnerability)
│       ├── test_mcp.py             ← MCP custom vulnerability
│       ├── test_dlp_integration.py ← proxy/dlp.py 統合テスト
│       └── baselines/
│           └── promptfoo-2026-05-09.json  ← 旧結果アーカイブ
└── pyproject.toml                  ← deepteam 追加
```

変更:

```
security-platform/
├── README.md                       ← Prerequisites / Red Team 節を更新
├── docs/DESIGN.md                  ← §6 Phase 4 / §7 ADR-lite に追記 (PR #113 が merge される前提、未 merge なら本 PR で書く)
├── scripts/
│   └── redteam.sh                  ← Phase D で redteam-legacy.sh に rename、Phase E で削除
├── Makefile                        ← `make redteam` を pytest に切替
└── .github/workflows/pr-security.yml  ← redteam job 追加 (Phase C)
```

削除予定 (Phase E):

```
security-platform/
├── .promptfoo/redteam.yaml         ← Phase E で削除
└── scripts/redteam-legacy.sh       ← Phase E で削除
```

### 4.5 Test Plan

- **Unit (`tests/redteam/unit/`)**:
  - `AnalystLLM` の `BaseLLM` 契約 (generate / agenerate)
  - MCP custom vulnerability の attack template 生成 (固定 seed で deterministic)
  - `reporter.py` の `RiskAssessment` → dict 変換
- **Integration (`tests/redteam/integration/`)**:
  - 実 LLM (Haiku / Gemini Flash) を使った 1 vulnerability × 1 attack の通し (CI でも実行、smoke)
  - `scan_results` への persist 確認 (in-memory SQLite)
  - `proxy/dlp.py` を import して PII output → DLP block の defense-in-depth テスト
- **Manual / E2E**:
  - [ ] 本 PR 後、ローカルで `pytest tests/redteam/ -v` を 3 回実行し flaky 度を観察
  - [ ] 既存 Promptfoo の最終 run を baseline として `tests/redteam/baselines/` に保存
  - [ ] CI で `pr-security.yml` の red team job が `continue-on-error: true` で動作する事を確認 (Phase C)

### 4.6 Migration / Rollback

- **Migration**: DB スキーマ変更なし (`scan_results` の `scan_type` enum 値追加のみ、SQLite なので app コードで吸収)
- **Rollback**: `scripts/redteam-legacy.sh` を残しておけば即時切戻し可能。`pyproject.toml` から `deepteam` を削除すれば `tests/redteam/` は import error で skip される
- **既存ユーザー影響**: `make redteam` の挙動が Phase A 〜 C で同一 (Promptfoo 実行)、Phase D で DeepTeam 実行に切替。Node.js 削除は Phase E

### 4.7 Feature Enablement

- env で切替不要 (テスト即実行)
- ただし CI gating は **段階的に有効化**:
  - Phase C: `continue-on-error: true` (失敗しても merge 可、観察用)
  - Phase D: `continue-on-error: false` (gating 有効化)
- 緊急時に gating を一時無効化したい場合: workflow file を直接編集 (`continue-on-error: true` 戻し)

---

## 5. Operational Concerns

### 5.1 Monitoring

- **CI 実行結果**: GitHub Actions の `pr-security.yml > redteam` job
- **ローカル**: `pytest tests/redteam/ -v --tb=short`
- **Dashboard**: `:8000/scan-results?type=redteam` で過去 run 一覧
- **Slack / LINE**: notifier の severity しきい値で重大な失敗のみ通知 (Phase D 以降)

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| `pytest tests/redteam/` が ModuleNotFoundError: deepteam | `uv sync --extra redteam` (extras に分離する場合) or 通常 deps 化 |
| simulator が Confident AI に request 送信 (telemetry) | `DEEPEVAL_TELEMETRY_OPT_OUT=YES` を CI workflow + `.env.example` に追記 |
| Vertex Gemini で rate limit | simulator/evaluator model を Haiku に切替 (`DEEPTEAM_SIMULATOR_MODEL=anthropic:claude-haiku-4-5`) |
| flaky な test (温度 > 0 で結果が揺れる) | seed 固定 + threshold をやや下げる (例: pass_rate >= 0.85) |
| MCP custom vulnerability が Promptfoo より緩い | `tests/redteam/baselines/promptfoo-*.json` と比較し attack template を追加 |

### 5.3 Dependencies

- **新規**: `deepteam>=0.x,<0.y` (具体 version は Phase A PR で確定)
- **既存利用**: `analyzer/llm_analyst.py` の Anthropic / Vertex client (再利用)
- **削除予定 (Phase E)**: `promptfoo` (npm)、Node.js 18+ (red team 用途のみ)
- **保持**: Node.js 18+ は `scan-mcp.sh` / `scan-skills.sh` で引き続き必要

### 5.4 Non-Functional Requirements

#### 性能
- **CI 実行時間**: smoke 構成で 3〜5 分以内 (各 vulnerability 1 test × 約 10 vulnerability)
- **full run (cron / 手動)**: 15〜30 分以内 (各 5 test、計 50 test)

#### コスト
- **LLM 呼出**: 1 test = simulator (1) + target (1) + evaluator (1) ≈ 3 calls
- **CI smoke (PR ごと)**: 30 calls × Haiku 換算 → ¥10 / PR
- **full run (週 1 cron)**: 150 calls × Haiku → ¥50 / 週、月 ¥200 程度
- **既存 Promptfoo (49 test) との比較**: ほぼ同等、target call 数で差分小

#### プライバシー / データ保持
- **PII 扱い**: simulator が生成する attack prompt に sample PII を含む可能性あり (e.g. fake email)。
  Confident AI Cloud には送らない (telemetry opt-out)。`scan_results` に保存される `findings` JSON
  は内部 SQLite のみ
- **保持期間**: `scan_results` は永続 (audit_logs と同じ retention 90 日にするか別途検討)

#### キャパシティ
- 1 PR = smoke 30 calls。CI 並行度を上げても LLM rate limit が先に当たるため、
  workflow 内で `pytest -n 0` (並列なし) で実行

---

## 6. Drawbacks

- **Promptfoo の `mcp` / `agentic:*` plugin の知見をロス**: コミュニティで磨かれた attack template
  を捨てる事になる。custom Vulnerability で代替するが、初期品質は劣る前提
- **HTML 自己完結レポートのロス**: Promptfoo の単一 HTML を gh-pages や artifact に貼る運用は不可能になる。
  Dashboard `:8000` は localhost 前提なので閲覧性で劣る
- **2 系統の併存期間**: Phase A〜D の間 (推定 1〜2 ヶ月) は両方の依存が pyproject.toml に存在する
- **DeepTeam の OSS 範囲が将来狭まるリスク**: Confident AI が cloud 製品強化のため OSS 機能を制限する
  可能性 (Apache 2.0 fork はできるが運用コストあり)

これらを踏まえても §1 (Summary) / §2 (Goals) のメリットが上回ると判断。特に **defense-in-depth の
1 テスト化** (`proxy/dlp.py` を直接 import) は Promptfoo では構造的に得られない利点。

## 7. Alternatives

### 案 A: Promptfoo 維持 + 改善

- **概要**: `redteam.sh` の出力を Python script で parse し `scan_results` に流し込む。Node.js 依存は維持
- **却下理由**:
  - 結局 Python 側で JSON parser を書く必要があり、DeepTeam を使うのと同等の Python 実装コスト
  - CI gating には依然として subprocess + parse の脆さが残る
  - DLP との 1-test 統合は不可能 (構造的制約)
  - Node.js 依存削減の利益が得られない

### 案 B: DeepTeam 主軸 + Promptfoo を `mcp` plugin のみ残す

- **概要**: DeepTeam で OWASP 主要カテゴリをカバーし、MCP 特化テストだけは Promptfoo の `mcp` plugin
  を呼び続ける
- **却下理由**:
  - 2 系統メンテのコスト (CI workflow 2 つ、依存 2 系統、結果 schema 2 種)
  - `mcp` plugin の中身を読んだ限り、custom Vulnerability で再現する工数 (推定 200〜400 行) は許容範囲
  - 統合検証 (DLP + MCP injection) を 1 テストで書けない問題が残る
- **採用条件**: Phase B PR で MCP custom Vulnerability の品質が baseline (Promptfoo) を著しく下回ると
  判明した場合、再評価する

### 案 C: 自前 red team フレームワーク

- **概要**: pytest + Anthropic SDK 直叩きで attack prompt を hand-craft
- **却下理由**:
  - DeepTeam が提供する synthesizer / multi-turn (Crescendo / Tree Jailbreak) を再実装するコストが過大
  - OWASP LLM Top 10 への mapping を自前で維持する事になる
  - 個人 / 家族規模の monorepo に対して overkill

### 案 D: Garak / NeMo Guardrails 等の他 OSS

- **概要**: NVIDIA Garak (red team) や NeMo Guardrails (runtime guardrail) に切替
- **却下理由**:
  - Garak は MCP / agentic に特化しておらず、汎用 LLM red team
  - NeMo Guardrails は runtime 防御層で red team とは目的が違う
  - DeepTeam が Confident AI / DeepEval エコシステム経由で metric framework を共有できるメリットを失う

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-09 | Draft | 初稿 (本 PR) |
