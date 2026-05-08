# security-platform

monorepo 内の AI エージェント (Claude Agent SDK / MCP / FastAPI 等) を対象に、
**サプライチェーン脆弱性監視 + MCP プロキシ防御 + 通知 + 監査** を一元提供する
セキュリティプラットフォーム。各エージェントは inventory に 1 行追加するだけで
OWASP ASI / OWASP LLM Top 10 のカバレッジを得られる。

> **Status**: Phase 1-3 完了 (collector / analyzer / notifier / MCP proxy / dashboard) / Phase 4 部分実装 (CI gating: gitleaks + bandit、pip-audit + snyk は計画中)

設計詳細 (機能要件 / 非機能要件 / アーキテクチャ / データモデル / Roadmap / ADR-lite / 用語集) は
[`docs/DESIGN.md`](docs/DESIGN.md) を参照。本 README は「動かす / 適用する」観点に絞る。

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 (推奨)、pip でも可 |
| Node.js | 18+ | MCP scan / Red team script に必要 |
| gcloud CLI | 最新 | Vertex AI Gemini を使う場合のみ |

### 0.2 セットアップ

```bash
cd agent_monorepo/security-platform

# 1. 依存インストール + .env 雛形 + DB 初期化を一括
make setup

# 個別にやる場合:
make install     # uv sync
make env         # cp config/.env.example → config/.env
make auth        # gcloud auth application-default login (Vertex 利用時)
make db-init     # SQLite 初期化
```

`config/.env` で LLM 分析用の認証情報を設定:

```env
# Claude を使う場合
ANTHROPIC_API_KEY=sk-ant-...

# Vertex AI Gemini を使う場合 (上記の代替)
VERTEX_AI_PROJECT=your-gcp-project
VERTEX_AI_LOCATION=us-central1
```

### 0.3 起動

```bash
make dashboard         # Web Dashboard → http://localhost:8000
make proxy             # MCP Proxy (MCP_TARGET_URL=http://localhost:3000 を指定)
```

### 0.4 単発実行

```bash
make collector         # NVD / GHSA / OSV / VulnerableMCP から CVE 取得
make analyzer          # inventory 照合 + LLM 分析 + 通知
make digest            # daily digest (severity 別件数サマリ)

make scan-mcp          # .mcp.json スキャン (uvx 必要)
make scan-skills       # skills/ ディレクトリのスキャン
make redteam           # Promptfoo Red team test (Node.js + ANTHROPIC_API_KEY)

make cron              # 定期実行を crontab に登録
```

### 0.5 テスト・静的解析

```bash
make test              # pytest
```

---

## 1. 主要コマンド・コンポーネント

| コマンド | 動作 | 詳細 |
|---|---|---|
| `make dashboard` | FastAPI Dashboard (port 8000) | `src/dashboard/app.py` |
| `make proxy` | MCP プロキシ (port 8080) | `src/proxy/server.py` |
| `make collector` | CVE 取得 (NVD/GHSA/OSV/VulnerableMCP) | `src/collector/main.py` |
| `make analyzer` | inventory 照合 + LLM 分析 + 通知 | `src/analyzer/main.py` |
| `make digest` | 日次 digest を Slack/LINE/Email へ | `src/notifier/digest.py` |
| `make scan-mcp` | `.mcp.json` を Snyk Agent Scan で検査 | `scripts/scan-mcp.sh` |
| `make scan-skills` | `skills/` ディレクトリを検査 | `scripts/scan-skills.sh` |
| `make redteam` | Promptfoo で Red team テスト | `scripts/redteam.sh` |
| `make cron` | 定期実行を `crontab -e` に追記 | `scripts/setup-cron.sh` |

各コンポーネントの責務 / モジュール分割 / データフローは
[`docs/DESIGN.md`](docs/DESIGN.md) §5 (アーキテクチャ) を参照。

---

## 2. 環境変数

主要なものだけ。詳細は `config/.env.example` 参照。

| 変数 | 既定 | 用途 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude を LLM 分析に使う場合 |
| `VERTEX_AI_PROJECT` | — | Vertex Gemini を使う場合 (ADC + project) |
| `VERTEX_AI_LOCATION` | `us-central1` | Vertex Gemini の region |
| `NVD_API_KEY` | — | NVD rate limit 緩和 (任意) |
| `GITHUB_TOKEN` | — | GitHub Advisory rate limit 緩和 (任意) |
| `SLACK_WEBHOOK_URL` | — | Slack 通知 |
| `LINE_CHANNEL_SECRET` | — | LINE Messaging API (Bot) |
| `LINE_CHANNEL_ACCESS_TOKEN` | — | LINE Messaging API (Bot) |
| `LINE_USER_IDS` | — | 通知先 userId の CSV |
| `MCP_TARGET_URL` | `http://localhost:3000` | proxy 経由の実 MCP server URL |

**LINE 通知について**: 旧 LINE Notify は 2025-03-31 でサービス終了済。本プラットフォームは
**LINE Messaging API (Bot channel)** を使う。`LINE_NOTIFY_TOKEN` 設定があっても無視される
(起動時に deprecation 警告)。詳細は [`docs/DESIGN.md`](docs/DESIGN.md) §5.3 を参照。

---

## 3. エージェントへのセキュリティレイヤ適用

monorepo 内の任意のエージェントに対して 4 つのレイヤを段階的に適用できる。

| レイヤ | 内容 | 必須度 |
|---|---|---|
| 1. Inventory 登録 | `config/inventory.yaml` に MCP server / 依存パッケージを宣言 | 必須 |
| 2. Scan 対象登録 | `config/scan.yaml` の `targets` に追加 | 必須 |
| 3. MCP Proxy | tool 呼出を proxy 経由にして DLP / Rate / Pinning を適用 | 推奨 |
| 4. 通知 | severity しきい値で Slack/LINE/Email 通知を有効化 | 任意 |

**最小構成 (監視のみ)**: Step 1 + 2 + 4 (collector + analyzer + 通知のみ)。Step 3 はスキップ可。

### 3.1 Step 1 — Inventory 登録

`config/inventory.yaml` に対象エージェントの MCP server / npm / pip パッケージを追加:

```yaml
mcp_servers:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    source: "npm"
    config_path: "your-agent-system/.mcp.json"   # monorepo ルートからの相対パス
    server_key: "your-server-key"                # .mcp.json 内のキー名
    tags: ["your", "tags"]

npm_packages:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    ecosystem: "npm"
```

analyzer が CVE をこの inventory と照合し、影響するエージェントだけに通知する。

### 3.2 Step 2 — Scan 対象登録

`config/scan.yaml` の `targets` に追加:

```yaml
targets:
  mcp_configs:
    - "your-agent-system/.mcp.json"
  skills_directories:
    - "your-agent-system/skills/"        # 無ければ省略
  source_directories:
    - "your-agent-system/src/"
```

`scripts/scan-mcp.sh` (Snyk Agent Scan) と Gitleaks がこの paths を対象にする。

### 3.3 Step 3 — MCP Proxy 適用

agent ↔ MCP server の間に proxy を挿入し、Rate Limit / DLP / Tool Pinning / Injection 検知 / Allowed destination filter を適用する。

```bash
# 1. proxy を起動
cd security-platform
MCP_TARGET_URL=http://localhost:<your-mcp-port> make proxy
```

```json
// 2. agent の .mcp.json を proxy 経由に変更
{
  "mcpServers": {
    "your-server": {
      "transport": "http",
      "url": "http://localhost:8080"
    }
  }
}
```

```yaml
# 3. config/scan.yaml で proxy mode を選択
gateway:
  mode: passive          # 1〜2 週間 passive で calibration → "active" に切替
  allowed_destinations:
    - "localhost"
    - "api.your-mcp-provider.com"
```

| Mode | 動作 | 推奨タイミング |
|---|---|---|
| `passive` | 違反を log のみ、トラフィックは通す | 導入直後 (false positive を観察) |
| `active` | 違反をブロック + 即時 alert | calibration 完了後 |

各防御層の詳細 (Tool Pinning / DLP / Rate Limiter / Injection) は
[`docs/DESIGN.md`](docs/DESIGN.md) §5.2 を参照。

### 3.4 Step 4 — 通知設定

`config/notification.yaml` で channel ごとの enable / severity しきい値を設定:

```yaml
channels:
  slack:
    enabled: true
    severity_threshold: HIGH    # CRITICAL/HIGH/MEDIUM/LOW
  line:
    enabled: true
    severity_threshold: CRITICAL
  email:
    enabled: false
```

### 3.5 動作確認

```bash
make collector && make analyzer
make dashboard               # http://localhost:8000 で確認
```

Dashboard で以下が見えること:
- inventory に対象エージェントの MCP server が表示
- audit_logs に proxy 経由の tool 呼出が記録 (Step 3 適用時)
- 脆弱性リストに CVE matching 結果

---

## 4. CI Security Scan

`.github/workflows/pr-security.yml` が PR 単位で `pr-tests.yml` と並列に実行される:

| Scanner | 対象 | merge ブロック条件 |
|---|---|---|
| **gitleaks** | PR の commit 範囲 | secret 検出 (allowlist は `.gitleaks.toml`) |
| **bandit** | 変更された `.py` (tests/ 除く) | medium+ severity & medium+ confidence |

両スキャナは SARIF を artifact として 7 日保管。

### 未統合 (Phase 4 計画)

| 項目 | 状態 | メモ |
|---|---|---|
| pip-audit / uv export CVE scan | ⏳ | `pyproject.toml` / `uv.lock` 変更時に依存 CVE をスキャン。無料・auth 不要 |
| snyk-agent-scan | ⏳ | MCP / Skill 専用。`SNYK_TOKEN` secret が必要 |
| `.gitleaks.toml` allowlist 調整 | ⏳ | 初回運用時に false positive を narrow `paths` で抑制 |
| Bandit severity ratchet (low まで) | ⏳ | medium+ をクリアしてから low に下げる |
| `scripts/scan-skills.sh` REPO_ROOT 修正 | ⏳ | `../../..` → `../..` (`scan-mcp.sh` と同様) |

設計判断 / これらの順序付けは [`docs/DESIGN.md`](docs/DESIGN.md) §7 (ADR-lite) を参照。

---

## 5. OWASP カバレッジ

| カテゴリ | コントロール |
|---|---|
| ASI01 Prompt Injection | Red team / proxy injection.py |
| ASI02 Excessive Permissions | Rate Limiter / DLP |
| ASI03 Broken Access Control | RBAC red team |
| ASI04 Supply Chain | NVD / GHSA / OSV / VulnerableMCP collector |
| ASI05 Session Hijacking | Tool Pinning (rug-pull 検知) |
| ASI06 Sensitive Data Exposure | proxy/dlp.py (全 tool パラメータ) |
| ASI07 Misinformation | Red team |
| ASI08 Overly Permissive Plugins | scan-mcp.sh (Snyk Agent Scan) |
| ASI09 Training Data Poisoning | 間接 injection テスト |
| ASI10 Model Theft / DoS | Rate Limit + Circuit Breaker |

---

## 6. 関連ドキュメント

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム全体設計 (機能要件 F1-F28 / NFR / アーキ / Roadmap / ADR-lite 15 件 / 用語集)
- [`config/inventory.yaml`](config/inventory.yaml) — 監視対象 MCP server / npm / pip パッケージ
- [`config/scan.yaml`](config/scan.yaml) — scan target / NVD keywords / proxy gateway 設定
- [`config/notification.yaml`](config/notification.yaml) — 通知 channel / severity しきい値
- [`scripts/`](scripts/) — scan-mcp / scan-skills / setup-cron / redteam
- [`../docs/PROPOSALS/`](../docs/PROPOSALS/) — モノレポ共通の per-feature proposal / ADR
- [`../docs/MIGRATION_PLAN.md`](../docs/MIGRATION_PLAN.md) — ドキュメント refactoring 全体計画
