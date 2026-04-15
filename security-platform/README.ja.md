# Agent Security Platform

AIエージェントシステム向けのセキュリティ監視プラットフォームです。MCPサーバー・スキル・依存パッケージの脆弱性を追跡します。

## 概要

このプラットフォームが提供する機能：

- **脆弱性収集** — NVD・GitHub Advisory・OSV・VulnerableMCP からCVEを取得
- **インベントリマッチング** — 登録済みMCPサーバー・パッケージと脆弱性を照合
- **通知** — Slack・LINE Notify・メールでアラートを送信
- **MCPプロキシ** — レート制限・ツールピニング（ラグプル検知）・DLPを適用
- **Webダッシュボード** — `http://localhost:8000`
- **レッドチームテスト** — Promptfoo による自動攻撃テスト

## 前提条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推奨）または pip
- Node.js 18+（MCPスキャンスクリプトおよびレッドチームテストに必要）

## クイックスタート

```bash
cd security-platform

# 1. 依存パッケージをインストール
uv sync

# 2. 環境変数を設定
cp config/.env.example config/.env
# config/.env を編集 — LLM分析を使う場合は最低限 ANTHROPIC_API_KEY を設定

# 3. データベースを初期化
uv run python -m src.db.migrations

# 4. ダッシュボードを起動
uv run uvicorn src.dashboard.app:app --host 0.0.0.0 --port 8000

# http://localhost:8000 をブラウザで開く
```

## 各コンポーネントの起動

### ダッシュボード（ポート 8000）
```bash
uv run uvicorn src.dashboard.app:app --reload
```

### MCPセキュリティプロキシ（ポート 8080）
```bash
uv run uvicorn src.proxy.server:app --port 8080
# MCP_TARGET_URL 環境変数に実際のMCPサーバーのURLを指定する
```

### 脆弱性コレクター（単発実行）
```bash
uv run python -m src.collector.main
```

### アナライザー（脆弱性の処理と通知）
```bash
uv run python -m src.analyzer.main
```

### デイリーダイジェスト
```bash
uv run python -m src.notifier.digest
```

### cronの自動設定
```bash
./scripts/setup-cron.sh
```

### MCPコンフィグスキャン（uvx が必要）
```bash
./scripts/scan-mcp.sh
```

### レッドチームテスト（Node.js と ANTHROPIC_API_KEY が必要）
```bash
./scripts/redteam.sh
```

## 設定ファイル

### `config/inventory.yaml`
使用しているMCPサーバー・スキル・パッケージをすべて登録します。アナライザーはこのインベントリを使って、あなたのスタックに影響する脆弱性を特定します。

### `config/scan.yaml`
NVDキーワード・DLPパターン・レート制限の閾値・スキャン対象を設定します。

### `config/notification.yaml`
通知チャネルの有効化・無効化と、通知する重大度の閾値を設定します。

### `config/.env`
APIキーなどの機密情報。`.env.example` からコピーして使用します。このファイルは絶対にコミットしないでください。

## エージェントシステムへのセキュリティレイヤー適用手順

このmonorepo内の任意のエージェントシステムに対してセキュリティレイヤーを適用する手順です。

### レイヤー概要

| レイヤー | 内容 | 必須 |
|---------|------|------|
| 1. インベントリ登録 | MCPサーバー・パッケージをCVE監視対象として登録 | 必須 |
| 2. スキャン対象登録 | 自動スキャンの対象にエージェントシステムを追加 | 必須 |
| 3. MCPプロキシ | ツール呼び出しにレート制限・DLP・ツールピニング・インジェクション検知を適用 | 推奨 |
| 4. 通知設定 | 脆弱性や違反検知時にアラートを受け取る | 任意 |

---

### Step 1 — インベントリに登録する

`config/inventory.yaml` を編集し、エージェントシステムのMCPサーバーとパッケージを追加します。

```yaml
mcp_servers:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    source: "npm"
    config_path: "your-agent-system/.mcp.json"  # monorepoルートからの相対パス
    server_key: "your-server-key"               # .mcp.json 内のキー名
    tags: ["your", "tags"]

npm_packages:
  - name: "@modelcontextprotocol/server-your-server"
    version: "latest"
    ecosystem: "npm"
```

アナライザーはこのインベントリを使って、取得したCVEをあなたのスタックと照合し、的確なアラートを生成します。

---

### Step 2 — スキャン対象として登録する

`config/scan.yaml` の `targets` セクションにエージェントシステムを追加します。

```yaml
targets:
  mcp_configs:
    - "your-agent-system/.mcp.json"

  skills_directories:
    - "your-agent-system/skills/"   # skillsディレクトリがない場合は省略

  source_directories:
    - "your-agent-system/src/"
```

これにより、自動MCPコンフィグスキャン（`scripts/scan-mcp.sh`）とGitleaksシークレットスキャンがエージェントシステムを対象に含めるようになります。

---

### Step 3 — MCPプロキシを適用する

プロキシはエージェントとMCPサーバーの間に置かれ、すべてのツール呼び出しに対してレート制限・DLP・ツールピニング・インジェクション検知を適用します。

**3-1. プロキシを起動する**

```bash
cd security-platform
MCP_TARGET_URL=http://localhost:<your-mcp-port> \
  uv run uvicorn src.proxy.server:app --port 8080
```

**3-2. エージェントの接続先をプロキシに変更する**

エージェントシステムの `.mcp.json` で、各MCPサーバーの接続先をプロキシURLに変更します。

変更前：
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

変更後（プロキシ経由のHTTPトランスポート）：
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

**3-3. プロキシのモードを選択する**

`config/scan.yaml` の `gateway.mode` を設定します。

| モード | 動作 | 推奨タイミング |
|--------|------|---------------|
| `passive` | 違反をログに記録するが通信はブロックしない | 導入直後の1〜2週間（ルール調整期間） |
| `active` | 違反をブロックし即時アラートを送信 | ルール調整完了後 |

```yaml
gateway:
  mode: passive   # 準備ができたら "active" に変更する
```

**3-4. 許可する接続先を設定する（activeモード）**

`config/scan.yaml` の `gateway.allowed_destinations` に、MCPサーバーが通信するホスト名を追加します。

```yaml
gateway:
  allowed_destinations:
    - "localhost"
    - "api.your-mcp-provider.com"
```

activeモードでは未登録の接続先へのリクエストがブロックされ、passiveモードではログに記録されます。

---

### Step 4 — コレクターとアナライザーを実行する

最新のCVEを取得し、登録済みインベントリと照合します。

```bash
cd security-platform

# NVD・GitHub Advisory・OSV・VulnerableMCP からCVEを取得
uv run python -m src.collector.main

# インベントリと照合してスコアリングし、通知を送信
uv run python -m src.analyzer.main
```

継続的な監視のためにcronを設定する場合：

```bash
./scripts/setup-cron.sh
```

---

### Step 5 — ダッシュボードで確認する

ダッシュボードを起動して `http://localhost:8000` を開きます。

```bash
uv run uvicorn src.dashboard.app:app --port 8000
```

以下を確認してください：
- エージェントシステムのMCPサーバーがインベントリビューに表示されている
- ツール呼び出しのログにプロキシ経由のトラフィックが記録されている
- 脆弱性リストにCVEマッチ結果が表示されている

---

### 最小構成（監視のみ・プロキシなし）

プロキシなしでCVE監視のみを行う場合は、Step 1・2・4のみで完結します。Step 3はスキップしてください。

---

## アーキテクチャ

```
security-platform/
├── src/
│   ├── collector/      # NVD・GitHub Advisory・OSV・VulnerableMCP からCVEを取得
│   ├── analyzer/       # インベントリと照合・重大度スコアリング・LLM分析
│   ├── notifier/       # Slack / LINE / メール通知とダイジェスト
│   ├── proxy/          # レート制限・DLP・ツールピニングを適用するMCPプロキシ
│   ├── dashboard/      # FastAPI Webダッシュボード
│   └── db/             # SQLAlchemyモデルとマイグレーション
├── config/             # YAML設定ファイル
├── scripts/            # スキャン・cronセットアップ用シェルスクリプト
├── logs/               # JSONLログ（.gitkeep以外はgitignore）
└── data/               # SQLiteデータベース（.gitkeep以外はgitignore）
```

## セキュリティコントロール

| コントロール | 場所 | 内容 |
|-------------|------|------|
| ツールピニング | `proxy/tool_pinning.py` | ハッシュベースの整合性チェック、ラグプル攻撃を検知 |
| DLP | `proxy/dlp.py` | ツールパラメータのAPIキー・認証情報・PII をスキャン |
| レート制限 | `proxy/rate_limiter.py` | ツール単位のスライディングウィンドウ＋サーキットブレーカー |
| 監査ログ | `proxy/server.py` | すべてのツール呼び出しをSQLiteとJSONLに記録 |

## カバレッジ — OWASP ASI / OWASP LLM Top 10

| カテゴリ | コントロール |
|---------|-------------|
| ASI01 プロンプトインジェクション | レッドチームテスト、間接インジェクション検知 |
| ASI02 過剰な権限 | プロキシのレート制限、DLP |
| ASI03 壊れたアクセス制御 | RBACレッドチームテスト |
| ASI04 サプライチェーン | OSV/NVD/GitHub Advisory監視 |
| ASI05 セッションハイジャック | ツールピニング（ラグプル検知） |
| ASI06 機密データの露出 | すべてのツールパラメータへのDLPエンジン適用 |
| ASI07 誤情報 | レッドチームテスト |
| ASI08 過剰に許可されたプラグイン | .mcp.json に対するSnyk Agent Scan |
| ASI09 学習データの汚染 | 間接インジェクションテスト |
| ASI10 モデル窃取 / DoS | レート制限、サーキットブレーカー |
