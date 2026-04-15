# Agent Security Platform

Security monitoring platform for AI agent systems — tracks vulnerabilities in MCP servers, skills, and dependencies.

## Overview

This platform provides:

- **Vulnerability collection** from NVD, GitHub Advisory, OSV, and VulnerableMCP
- **Inventory matching** against your registered MCP servers and packages
- **Notifications** via Slack, LINE Notify, and email
- **MCP Proxy** with rate limiting, tool pinning (rug-pull detection), and DLP
- **Web dashboard** at `http://localhost:8000`
- **Red team testing** via Promptfoo

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Node.js 18+ (for MCP scan scripts and red team)

## Quick Start

```bash
cd security-platform

# 1. Install dependencies
uv sync

# 2. Configure environment
cp config/.env.example config/.env
# Edit config/.env — set one of the following for LLM analysis:
#   Claude:    ANTHROPIC_API_KEY
#   Gemini:    VERTEX_AI_PROJECT + VERTEX_AI_LOCATION (uses Application Default Credentials)
#              Run: gcloud auth application-default login

# 3. Initialize the database
uv run python -m src.db.migrations

# 4. Start the dashboard
uv run uvicorn src.dashboard.app:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000
```

## Running Components

### Dashboard (Port 8000)
```bash
uv run uvicorn src.dashboard.app:app --reload
```

### MCP Security Proxy (Port 8080)
```bash
uv run uvicorn src.proxy.server:app --port 8080
# Set MCP_TARGET_URL env var to point at your real MCP server
```

### Vulnerability Collector (run once)
```bash
uv run python -m src.collector.main
```

### Analyzer (process collected vulns + notify)
```bash
uv run python -m src.analyzer.main
```

### Daily Digest
```bash
uv run python -m src.notifier.digest
```

### Automated Cron Setup
```bash
./scripts/setup-cron.sh
```

### MCP Config Scan (requires uvx)
```bash
./scripts/scan-mcp.sh
```

### Red Team Testing (requires Node.js + ANTHROPIC_API_KEY)
```bash
./scripts/redteam.sh
```

## Configuration

### `config/inventory.yaml`
Register all MCP servers, skills, and packages you use. The analyzer uses this to flag vulnerabilities that affect your specific stack.

### `config/scan.yaml`
Controls NVD keywords, DLP patterns, rate limiter thresholds, and scan targets.

### `config/notification.yaml`
Enable/disable notification channels and configure severity thresholds.

### `config/.env`
API keys and secrets. Copy from `.env.example`. Never commit this file.

## Applying Security Layers to an Agent System

This section explains how to apply each security layer to any agent system inside this monorepo.

### Overview of layers

| Layer | What it does | Required? |
|-------|-------------|-----------|
| 1. Inventory registration | Declare your MCP servers and packages for CVE monitoring | Yes |
| 2. Scan target registration | Include your agent system in automated scans | Yes |
| 3. MCP Proxy | Intercept all MCP tool calls for rate limiting, DLP, tool pinning, and injection detection | Recommended |
| 4. Notifications | Receive alerts when vulnerabilities or violations are detected | Optional |

---

### Step 1 — Register your inventory

Edit `config/inventory.yaml` and add your agent system's MCP servers and packages.

```yaml
mcp_servers:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    source: "npm"
    config_path: "your-agent-system/.mcp.json"  # path from monorepo root
    server_key: "your-server-key"               # key name inside .mcp.json
    tags: ["your", "tags"]

npm_packages:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    ecosystem: "npm"
```

The analyzer uses this inventory to match fetched CVEs against your specific stack and generate targeted alerts.

---

### Step 2 — Register as a scan target

Edit `config/scan.yaml` and add your agent system to the `targets` section:

```yaml
targets:
  mcp_configs:
    - "your-agent-system/.mcp.json"

  skills_directories:
    - "your-agent-system/skills/"   # omit if no skills directory

  source_directories:
    - "your-agent-system/src/"
```

This ensures the automated MCP config scan (`scripts/scan-mcp.sh`) and Gitleaks secret scan cover your agent system.

---

### Step 3 — Apply the MCP Proxy

The proxy sits between your agent and its MCP servers. It enforces rate limiting, DLP, tool pinning, and injection detection on every tool call.

**3-1. Start the proxy**

```bash
cd security-platform
MCP_TARGET_URL=http://localhost:<your-mcp-port> \
  uv run uvicorn src.proxy.server:app --port 8080
```

**3-2. Point your agent at the proxy**

In your agent system's `.mcp.json`, change each MCP server entry to use the proxy URL instead of the original server URL.

Before:
```json
{
  "mcpServers": {
    "your-server": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-your-server"]
    }
  }
}
```

After (HTTP transport via proxy):
```json
{
  "mcpServers": {
    "your-server": {
      "transport": "http",
      "url": "http://localhost:8080"
    }
  }
}
```

**3-3. Choose proxy mode**

Edit `config/scan.yaml` — `gateway.mode`:

| Mode | Behaviour | When to use |
|------|-----------|-------------|
| `passive` | Logs violations, does not block traffic | First 1–2 weeks while calibrating rules |
| `active` | Blocks violations and alerts immediately | After calibration |

```yaml
gateway:
  mode: passive   # change to "active" when ready
```

**3-4. Tune allowed destinations (active mode)**

Add the hostnames your MCP servers connect to under `gateway.allowed_destinations` in `config/scan.yaml`:

```yaml
gateway:
  allowed_destinations:
    - "localhost"
    - "api.your-mcp-provider.com"
```

Requests to unlisted destinations are blocked in active mode, logged in passive mode.

---

### Step 4 — Run the collector and analyzer

Fetch the latest CVEs and match them against your registered inventory:

```bash
cd security-platform

# Fetch CVEs from NVD, GitHub Advisory, OSV, VulnerableMCP
uv run python -m src.collector.main

# Match against inventory, score, and send notifications
uv run python -m src.analyzer.main
```

For ongoing monitoring, set up a cron job:

```bash
./scripts/setup-cron.sh
```

---

### Step 5 — Verify in the dashboard

Open `http://localhost:8000` after starting the dashboard:

```bash
uv run uvicorn src.dashboard.app:app --port 8000
```

Check that:
- Your agent system's MCP servers appear in the inventory view
- Tool call logs show traffic passing through the proxy
- Any CVE matches appear in the vulnerability list

---

### Minimal setup (monitoring only, no proxy)

If you only want CVE monitoring without the proxy layer, Steps 1, 2, and 4 are sufficient. Skip Step 3.

---

## Architecture

```
security-platform/
├── src/
│   ├── collector/      # Fetch CVEs from NVD, GitHub Advisory, OSV, VulnerableMCP
│   ├── analyzer/       # Match to inventory, score severity, run LLM analysis
│   ├── notifier/       # Slack / LINE / Email notifications and digests
│   ├── proxy/          # MCP proxy with rate limiting, DLP, tool pinning
│   ├── dashboard/      # FastAPI web dashboard
│   └── db/             # SQLAlchemy models and migrations
├── config/             # YAML configuration files
├── scripts/            # Shell scripts for scans and cron
├── logs/               # JSONL logs (gitignored except .gitkeep)
└── data/               # SQLite database (gitignored except .gitkeep)
```

## Security Controls

| Control | Location | Description |
|---------|----------|-------------|
| Tool Pinning | `proxy/tool_pinning.py` | Hash-based integrity check, detects rug pull attacks |
| DLP | `proxy/dlp.py` | Scans tool parameters for API keys, credentials, PII |
| Rate Limiting | `proxy/rate_limiter.py` | Per-tool sliding window + circuit breaker |
| Audit Log | `proxy/server.py` | All tool calls logged to SQLite and JSONL |

## Coverage — OWASP ASI / OWASP LLM Top 10

| Category | Control |
|----------|---------|
| ASI01 Prompt Injection | Red team tests, indirect injection detection |
| ASI02 Excessive Permissions | Proxy rate limiting, DLP |
| ASI03 Broken Access Control | RBAC red team tests |
| ASI04 Supply Chain | OSV/NVD/GitHub Advisory monitoring |
| ASI05 Session Hijacking | Tool pinning (rug pull detection) |
| ASI06 Sensitive Data Exposure | DLP engine on all tool parameters |
| ASI07 Misinformation | Red team tests |
| ASI08 Overly Permissive Plugins | Snyk Agent Scan on .mcp.json |
| ASI09 Training Data Poisoning | Indirect injection tests |
| ASI10 Model Theft / DoS | Rate limiting, circuit breaker |
