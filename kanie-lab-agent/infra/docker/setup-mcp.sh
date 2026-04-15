#!/bin/bash
# MCPサーバーのセットアップスクリプト
# Claude Agent SDKのMCP設定ファイルを生成する

set -e

CLAUDE_CONFIG_DIR="${HOME}/.claude"
MCP_CONFIG_FILE="${CLAUDE_CONFIG_DIR}/mcp_config.json"

mkdir -p "${CLAUDE_CONFIG_DIR}"

echo "MCPサーバーの設定を生成中..."

cat > "${MCP_CONFIG_FILE}" << 'EOF'
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
    }
  }
}
EOF

echo "MCPサーバー設定を ${MCP_CONFIG_FILE} に保存しました。"
echo ""
echo "設定済みのMCPサーバー:"
echo "  - brave-search (Brave検索)"
echo "  - fetch (Webページ取得)"
echo "  - paper-search (論文検索)"
echo "  - arxiv (arXiv論文)"
echo "  - semantic-scholar (Semantic Scholar)"
echo "  - estat (e-Stat政府統計)"
echo "  - e-gov-law (e-Gov法令検索)"
echo ""
echo "Google検索MCPは別途 tools/google-search-mcp/ を参照してください。"
