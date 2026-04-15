#!/bin/sh
set -e

# workspace の所有権を修正（Cloud Run は root で起動するため）
mkdir -p /app/workspace/users
chown -R appuser:appuser /app/workspace

# Claude OAuth 認証情報をセットアップ
mkdir -p /home/appuser/.claude
if [ -f /tmp/claude_credentials.json ]; then
  cp /tmp/claude_credentials.json /home/appuser/.claude/credentials.json
  chown appuser:appuser /home/appuser/.claude/credentials.json
  chmod 600 /home/appuser/.claude/credentials.json
fi

# MCP config を環境変数の実際の値で動的生成
# (setup-mcp.sh はリテラル文字列 ${VAR} を埋め込むため、本番では本スクリプトが生成する)
cat > /home/appuser/.claude/mcp_config.json << EOF
{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      }
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "paper-search": {
      "command": "uvx",
      "args": ["mcp-paper-search"]
    },
    "arxiv": {
      "command": "uvx",
      "args": ["mcp-arxiv"]
    },
    "semantic-scholar": {
      "command": "uvx",
      "args": ["mcp-semantic-scholar"],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "${SEMANTIC_SCHOLAR_API_KEY}"
      }
    },
    "estat": {
      "command": "uvx",
      "args": ["mcp-estat"],
      "env": {
        "ESTAT_APP_ID": "${ESTAT_APP_ID}"
      }
    },
    "e-gov-law": {
      "command": "uvx",
      "args": ["mcp-e-gov-law"]
    },
    "google-search": {
      "command": "python",
      "args": ["/app/mcp/google_search_server.py"],
      "env": {
        "GOOGLE_CLOUD_PROJECT": "${GOOGLE_CLOUD_PROJECT}"
      }
    }
  }
}
EOF

chown appuser:appuser /home/appuser/.claude/mcp_config.json
chmod 600 /home/appuser/.claude/mcp_config.json

exec gosu appuser "$@"
