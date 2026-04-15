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
# Edit config/.env — at minimum, set ANTHROPIC_API_KEY if you want LLM analysis

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
