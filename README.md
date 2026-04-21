# agent_monorepo

エージェント関連のプロジェクトコード一式。各サブプロジェクトは独立して開発・デプロイ可能だが、共通のセキュリティ基盤 (`security-platform`) 配下で脆弱性監視と MCP トラフィック検査を行う。

## プロジェクト一覧

| プロジェクト | 種別 | 概要 | 分析基盤連携 |
|---|---|---|---|
| [`kanie-lab-agent`](./kanie-lab-agent/) | 実装 | 慶應 SFC 蟹江研究室 大学院入試準備の研究支援エージェント | ⬜ 未着手 |
| [`stock-analysis-agent`](./stock-analysis-agent/) | 実装 | 日本株・米国株のテクニカル/ファンダメンタル/センチメント統合分析エージェント | ✅ 連携済 (PR #26) |
| [`lifeplanner-agent`](./lifeplanner-agent/) | 実装 | Money Forward ME 起点の家族向けライフプランニング・30年シミュレーションエージェント | ✅ 連携済 (PR #27) |
| [`security-platform`](./security-platform/) | 基盤 | 全エージェント共通のセキュリティ基盤（MCP Proxy / CVE 監視 / DLP / Red Team） | — (基盤側) |
| [`analytics-platform`](./analytics-platform/) | 基盤 | 全エージェント横断の分析基盤（OTel + Phoenix + JSONL + DuckDB + dbt、ローカル版のみ） | — (基盤側、Phase 1-4 完了 / Phase 5+ 未着手) |
| [`agent-system-1`](./agent-system-1/) | ダミー | 雛形（Research Assistant スキル用スケルトン） | — |
| [`agent-system-2`](./agent-system-2/) | ダミー | 雛形（Code Helper スキル用スケルトン） | — |

---

## 各エージェントの機能サマリ

### `kanie-lab-agent` — 蟹江研究室 大学院入試準備エージェント

慶應 SFC 政策・メディア研究科 蟹江憲史研究室（SDGs / 環境政策ガバナンス）への入学を目指す志願者を支援する Web アプリケーション。

**主な機能**
- **研究テーマ設計支援**: SDGs・環境政策・子ども政策の研究テーマ検討
- **論文サーベイ**: arxiv / Semantic Scholar / paper-search / e-Stat / e-Gov 法令を横断
- **面接対策**: 研究計画の模擬面接と厳格なフィードバック
- **研究計画レビュー**: 7軸評価による改善支援（追加引用の実在を MCP で確認）

**スタック**: Next.js 15 / FastAPI / Claude Agent SDK (Claude Sonnet 4.6) / Firebase Auth + Firestore / MCP (google-search, brave-search, paper-search, arxiv, semantic-scholar, e-stat, e-gov-law, fetch)

詳細: [`kanie-lab-agent/README.md`](./kanie-lab-agent/README.md)

---

### `stock-analysis-agent` — 株価分析エージェント

日本株（東証）・米国株（NASDAQ/NYSE）を対象に、企業名/ティッカーから自動で銘柄解決し、テクニカル・ファンダメンタル・センチメントを統合した日本語分析レポートを生成するエージェント。

**主な機能**
- **ティッカー解決**: 正規表現 → ローカル辞書 → yfinance Search → LLM の4段フォールバック
- **データ収集**: yfinance による日次 OHLCV・ファンダメンタルズ、Brave Search MCP 経由のニュース/センチメント
- **テクニカル指標**: SMA / EMA / RSI / MACD / ボリンジャーバンド（純 pandas 実装）
- **チャート生成**: mplfinance でローソク足 + 指標の画像出力
- **LLM 統合解説**: Claude Opus 4.6 (Vertex AI) が日本語で統合レポート生成
- **ユニバーススクリーナー**: 日本株 / 米国株 / グロース銘柄の一括スクリーニング（`data/universe/*.json`）

**スタック**: Python 3.12 / FastAPI / Claude Agent SDK (Claude Opus 4.6 via Vertex AI) / yfinance / pandas / mplfinance / SQLite / MCP (brave-search)

詳細: [`stock-analysis-agent/README.md`](./stock-analysis-agent/README.md)

---

### `lifeplanner-agent` — ライフプランナーエージェント

Money Forward ME の家計データを起点に、家族単位で30〜50年のキャッシュフロー・純資産推移をシミュレーションし、ライフイベント（出産・住宅購入・車買替等）の影響を定量比較する対話型エージェント。

**主な機能**
- **MF ME CSV 取込**: 収入・支出詳細 CSV を Shift-JIS/UTF-8 自動判定で取込
- **ダッシュボード**: 月次サマリ・カテゴリ別集計・異常検知・純資産スナップショット
- **世帯プロファイル管理**: メンバー/資産/負債の CRUD
- **ライフイベントシミュレーション**: 住宅購入 (E02)・車買替 (E04) を Phase 2 で実装済。Phase 4 で出産・進学・転職等を順次追加
- **30年プロジェクション**: 決定論的な長期シナリオ試算（給与成長率・インフレ率・投資利回り）
- **シナリオ比較**: 複数シナリオの決定論的差分 + LLM 自然言語要約
- **日本税制**: 所得税・住民税・社保（2026 年版 YAML、年版管理）
- **LLM アドバイザー**: Anthropic API 直呼 / GCP Vertex AI を `LLM_PROVIDER` で切替

**スタック**: Python 3.12 / FastAPI / SQLAlchemy async / Alembic / Anthropic SDK (Claude Sonnet 4.6、Vertex AI オプション) / Docker Compose / PostgreSQL (本番) / SQLite (ローカル)

詳細: [`lifeplanner-agent/README.md`](./lifeplanner-agent/README.md)

---

### `security-platform` — エージェントセキュリティ基盤

全エージェント共通のセキュリティ監視・防御基盤。各エージェントの MCP トラフィックをプロキシ経由に集約し、脆弱性 CVE を継続監視する。

**主な機能**
- **CVE 監視**: NVD / GitHub Advisory / OSV / VulnerableMCP から脆弱性を収集し、`config/inventory.yaml` 記載のコンポーネントと照合
- **MCP Proxy (Gateway)**: 各エージェントの MCP 呼出を中継し、レート制限・ツールピニング（rug-pull 検知）・DLP・プロンプトインジェクション検出を実施
- **通知**: Slack / LINE Notify / メールで脆弱性・違反を通知
- **Dashboard**: `http://localhost:8000` で脆弱性・ツール呼出ログ・インベントリを可視化
- **Red Team**: Promptfoo による敵対的テスト

**スタック**: Python 3.12 / FastAPI / SQLite / uvicorn / Node.js (MCP scan) / Promptfoo

詳細: [`security-platform/README.md`](./security-platform/README.md)

---

## 全体アーキテクチャ

```
┌──────────────────────────────────────────────────────────┐
│ User (Web / LINE)                                        │
└────────────────────────┬─────────────────────────────────┘
                         ↓
      ┌──────────────────┴──────────────────┐
      ↓                  ↓                  ↓
┌─────────────┐  ┌────────────────┐  ┌────────────────┐
│ kanie-lab-  │  │ stock-analysis-│  │ lifeplanner-   │
│ agent       │  │ agent          │  │ agent          │
│ (FastAPI)   │  │ (FastAPI)      │  │ (FastAPI)      │
└──────┬──────┘  └────────┬───────┘  └───────┬────────┘
       │  MCP tool calls  │                  │
       ↓                  ↓                  │
┌──────────────────────────────────────┐     │
│ security-platform MCP Proxy :8080    │     │
│  (rate limit / DLP / tool pinning /  │     │
│   injection detection / audit log)   │     │
└──────┬───────────────────────────────┘     │
       ↓                                     │
┌──────────────────────────────────────┐     │
│ External MCP Servers                 │     │
│  brave-search / google-search /      │     │
│  arxiv / semantic-scholar / e-Stat   │     │
│  / e-Gov-law / fetch / playwright    │     │
└──────────────────────────────────────┘     │
                                             ↓
                              ┌────────────────────────────┐
                              │ Anthropic / Vertex AI      │
                              │  (Claude Sonnet / Opus)    │
                              └────────────────────────────┘

   ┌──────────────────────────────────────┐
   │ security-platform Collector/Analyzer │ ← cron で CVE を定期取得・照合
   │ → Dashboard :8000 / Notifier         │
   └──────────────────────────────────────┘
```

---

## 共通開発ルール

| 項目 | 内容 |
|---|---|
| Python | 3.12+ |
| パッケージ管理 | uv |
| ブランチ戦略 | `feature/*` → PR → main マージ（main への直接 push 禁止） |
| LLM | Anthropic Claude (直呼 or Vertex AI)。`LLM_PROVIDER` で切替 |
| MCP | 可能な限り `security-platform` の MCP Proxy (`http://localhost:8080`) 経由 |
| シークレット | `.env` は gitignore。`.env.example` にキー一覧のみ記載 |
| セキュリティ | 新規エージェント追加時は `security-platform/config/inventory.yaml` と `scan.yaml` に登録 |

---

## 新規エージェント追加手順

1. `<agent-name>/` ディレクトリ作成（`pyproject.toml` / `Dockerfile` / `README.md`）
2. MCP を使う場合は `security-platform/config/inventory.yaml` の `mcp_servers` と `npm_packages` に登録
3. `security-platform/config/scan.yaml` の `targets.source_directories` / `mcp_configs` に追加
4. MCP クライアント設定で `transport: "http"` / `url: "http://localhost:8080"` を指定（プロキシ経由）
5. CVE / gitleaks / MCP config スキャンが CI で回ることを確認

詳細: [`security-platform/README.md`](./security-platform/README.md#applying-security-layers-to-an-agent-system)

---

## ライセンス

[LICENSE](./LICENSE) 参照。
