# security-platform 設計書

| | |
|---|---|
| **Version** | 1.0 |
| **最終更新** | 2026-05-08 |
| **Status** | Active (Phase 1-3 完了 / Phase 4 部分実装) |
| **Owner** | @kurama554101 |
| **Type** | 共通基盤 (monorepo 内全エージェントの脆弱性監視 + MCP プロキシ + 通知) |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2025-初版 | (初版) | README に集約 |
| 2026-05-08 | 1.0 | `docs/SYSTEM_DESIGN_TEMPLATE.md` 準拠で設計内容を README から分離 |

---

## 0. Executive Summary

monorepo 内の AI エージェントシステム (Claude Agent SDK / MCP / FastAPI 等) を対象に、
**サプライチェーン脆弱性監視 + MCP ツール呼出のランタイム防御 + 通知 + 監査** を一元提供する
セキュリティプラットフォーム。各エージェントは inventory + scan 対象を YAML に登録し、
任意で MCP プロキシを挟むだけで OWASP ASI / OWASP LLM Top 10 のカバレッジを得られる。

- **収集**: NVD / GitHub Advisory / OSV / VulnerableMCP の 4 ソースから CVE を定期取得
- **照合**: `config/inventory.yaml` の MCP server / npm / pip パッケージとマッチ → LLM (Claude / Vertex Gemini) で要約・対応推奨
- **防御**: MCP Proxy (Tool Pinning / DLP / Rate Limit / Injection 検知) を agent ↔ MCP server の間に挿入
- **通知**: Slack / LINE Messaging API / Email、severity しきい値で絞り込み
- **可視化**: FastAPI ダッシュボード (`localhost:8000`)
- **CI 連携**: PR 単位で gitleaks + bandit を実行 (`.github/workflows/pr-security.yml`)

---

## 1. 目的・スコープ

### 1.1 目的

- monorepo 全エージェントの **脆弱性監視を 1 箇所に集約** (各エージェントで Snyk/Dependabot を分散運用しない)
- MCP の特殊な脅威 (rug-pull / tool injection / 過剰権限) に対応した **ランタイム防御層** を提供
- LLM-as-a-Judge によって **担当者に届く粒度** で alert を出す (raw CVE 大量送信を避ける)
- monorepo 内なら inventory に 1 行追加するだけで保護対象に組み込める **低摩擦の onboarding**

### 1.2 想定ユーザー

| 種別 | 内容 |
|---|---|
| 主要 | monorepo 内の各エージェント開発者 (LINE bot / Cloud Run agent 等の owner) |
| 副次 | プラットフォーム保守者 (本人、CVE/Advisory を triage する) |
| 想定外 | 外部組織 / マルチテナント SaaS / 顧客企業の脆弱性管理 |

### 1.3 スコープ / Non-Goals

**やること**:
- CVE 自動収集 + inventory 照合 + LLM 分析 + 通知
- MCP プロキシ (rug-pull / DLP / Rate Limit / Injection 検知 / Audit Log)
- Promptfoo による Red team テスト
- PR タイムの gitleaks / bandit 実行 (CI gating)
- SQLite ベースの軽量ダッシュボード

**やらないこと (Non-Goals)**:
- IDS / IPS のような network-level 防御 (cloud provider の機能に委ねる)
- アプリ層の脆弱性スキャン (ZAP/Burp 等は別系)
- マルチテナント運用 / SaaS 化
- HIPAA / PCI-DSS 等の規制準拠
- secret rotation 自動化 (検知のみ、ローテーションは手動運用)

---

## 2. 機能要件

| ID | 機能 | 状態 | Phase | Proposal |
|---|---|---|---|---|
| F1 | NVD CVE collector (keywords filter) | ✅ 実装済 | Phase 1 | — |
| F2 | GitHub Advisory collector (npm/pip/go ecosystem) | ✅ 実装済 | Phase 1 | — |
| F3 | OSV collector (npm/PyPI/Go) | ✅ 実装済 | Phase 1 | — |
| F4 | VulnerableMCP collector (MCP-specific advisory) | ✅ 実装済 | Phase 2 | — |
| F5 | Inventory matching (`config/inventory.yaml` ↔ CVE) | ✅ 実装済 | Phase 1 | — |
| F6 | CVSS scoring + severity bucket (CRITICAL/HIGH/MEDIUM/LOW) | ✅ 実装済 | Phase 1 | — |
| F7 | LLM analysis (attack_summary / applicability / recommended_actions) | ✅ 実装済 | Phase 2 | — |
| F8 | Slack 通知 (webhook) | ✅ 実装済 | Phase 1 | — |
| F9 | LINE 通知 (Messaging API、旧 LINE Notify は廃止) | ✅ 実装済 | Phase 2 | — |
| F10 | Email 通知 (SMTP) | ✅ 実装済 | Phase 1 | — |
| F11 | Daily digest (severity 別件数サマリ) | ✅ 実装済 | Phase 2 | — |
| F12 | MCP Proxy: Tool Pinning (rug-pull 検知) | ✅ 実装済 | Phase 3 | — |
| F13 | MCP Proxy: DLP (API key / credential / PII 検出) | ✅ 実装済 | Phase 3 | — |
| F14 | MCP Proxy: Rate Limit (sliding window + circuit breaker) | ✅ 実装済 | Phase 3 | — |
| F15 | MCP Proxy: Injection 検知 (prompt injection patterns) | ✅ 実装済 | Phase 3 | — |
| F16 | MCP Proxy: passive / active mode 切替 | ✅ 実装済 | Phase 3 | — |
| F17 | MCP Proxy: Allowed destination filter | ✅ 実装済 | Phase 3 | — |
| F18 | Audit Log (tool 呼出を SQLite + JSONL に保存) | ✅ 実装済 | Phase 3 | — |
| F19 | FastAPI Dashboard (脆弱性 / inventory / audit log 表示) | ✅ 実装済 | Phase 2 | — |
| F20 | Red team test (Promptfoo + 攻撃シナリオ) | ✅ 実装済 | Phase 3 | — |
| F21 | Cron 自動化 (`scripts/setup-cron.sh`) | ✅ 実装済 | Phase 2 | — |
| F22 | gitleaks CI gating | ✅ 実装済 | Phase 4 | — |
| F23 | bandit CI gating (changed `.py` files、medium+ severity) | ✅ 実装済 | Phase 4 | — |
| F24 | pip-audit / uv export CVE scan (CI) | ⏳ 計画中 | Phase 4 | — |
| F25 | snyk-agent-scan CI 統合 (要 SNYK_TOKEN) | ⏳ 計画中 | Phase 4 | — |
| F26 | Bandit severity ratchet (low まで catch) | ⏳ 計画中 | Phase 4 | — |
| F27 | `scripts/scan-skills.sh` REPO_ROOT 修正 | ⏳ 計画中 | Phase 4 | — |
| F28 | Cloud デプロイ (Cloud Run / GKE) | ⬜ 未着手 | Phase 5+ | — |

---

## 3. 非機能要件 (NFR)

### 3.1 性能

- **MCP Proxy のオーバーヘッド**: tool 呼出 1 回あたり < 50ms (DLP regex + Rate Limit lookup)
- **Collector**: NVD/Advisory/OSV を直列で取得しても 5 分以内 (lookback 7 日想定)
- **LLM 分析**: 1 CVE あたり 1 LLM 呼出 (Haiku/Gemini)、5〜15 秒/件
- **Dashboard**: 表示は SQLite 直接 + Jinja、p95 < 200ms

### 3.2 可用性

- **MCP Proxy**: 単一プロセス FastAPI、家族・個人運用で 99% 想定。proxy ダウン時は agent 側が target に直接繋ぐフォールバックは無し (active mode は明示的に止める)
- **Collector / Analyzer**: cron で 1 時間〜2 時間おき。1〜2 回失敗しても次回で recovery する設計 (idempotent)
- **Dashboard**: 停止しても監視は継続 (collector + notifier は独立)

### 3.3 セキュリティ

- **認証**: ローカル運用前提のため Dashboard / Proxy には auth なし。公開時は Cloud IAP 等を前提
- **secret 管理**: `config/.env` (gitignore) または Secret Manager。`.env.example` のみコミット
- **PII の扱い**: tool 呼出の引数を Audit Log に保存するため DLP で API key / credential / 個人情報をマスク
- **LLM への送信内容**: CVE description / inventory metadata のみ (PII 含まず)

### 3.4 コスト

- **ローカル運用**: 月額ゼロ (SQLite + ローカル proxy)
- **LLM 分析**: 1 日 10〜50 件想定 → Haiku 換算で月 ¥100〜500
- **Cloud 展開時** (将来): Cloud Run + Cloud SQL + Secret Manager で月 ¥1,000〜2,000 想定

### 3.5 プライバシー / データ保持

- **vulnerabilities テーブル**: 永続 (履歴として残す)
- **audit_logs**: 90 日保持 (cron で削除、現状は手動)
- **JSONL ログ** (`logs/`): rotate せず append、運用者が定期削除
- **inventory**: コミットされる public 情報 (内部の MCP server 名 / npm パッケージのみ、credential なし)

### 3.6 キャパシティ

- **対象エージェント数**: 現在 9 (analytics / lifeplanner / piyolog / driving-license-bot / stock / tech-news / hotcook / kanie-lab / llm-client) → 100 まではスケール想定
- **DB サイズ上限**: SQLite 1 GB を目安、超えたら PostgreSQL 移行 (Phase 5+)
- **MCP Proxy 同時接続**: FastAPI default (uvicorn worker × CPU)、1 worker で十分

### 3.7 保守性 / テスト性

- **カバレッジ目標**: 全体 80%、`proxy/` は DLP / Rate Limit が要なので 90%
- **lint**: ruff (`ruff check src/ tests/`)
- **type check**: 未強制 (Pydantic / SQLAlchemy で実用上 OK)
- **observability**: 自分自身は analytics-platform に計装していない (循環依存回避)。Audit Log で代替

---

## 4. データモデル

```
vulnerabilities (CVE/Advisory)
    │  source / cve_id / ghsa_id / severity / cvss_score
    │  affected_component_* / matched_components / inventory_match
    │  attack_summary / applicability / recommended_actions   (LLM 出力)
    │  notification_sent / notification_sent_at
    └──▶ matches against ──▶ components

components (inventory.yaml に対応)
    │  name / version / ecosystem / source / config_path / tags

scan_results (scripts/scan-* の出力)
    │  scan_type / target_path / findings (JSON) / ran_at

audit_logs (proxy が記録)
    │  tool_name / input_args (DLP マスク済) / decision (allow/block)
    │  reason / latency_ms / requested_at

tool_pins (MCP tool の hash 固定)
    │  tool_name / fingerprint (sha256) / pinned_at / last_seen_at
```

### 4.1 主要テーブル

| テーブル | 用途 | 主キー | 関連 |
|---|---|---|---|
| `vulnerabilities` | CVE/Advisory 全件 + LLM 分析結果 + 通知状態 | id | matched_components → components.name |
| `components` | inventory.yaml をロードした正規化テーブル | id | — |
| `scan_results` | gitleaks / scan-mcp / scan-skills の結果 | id | — |
| `audit_logs` | MCP proxy が捕捉した tool 呼出全件 | id | — |
| `tool_pins` | tool fingerprint (rug-pull 検知用) | id | tool_name 単位で 1 行 |

詳細スキーマは [`src/db/models.py`](../src/db/models.py) (159 行) 参照。マイグレーションは `src/db/migrations.py` (`create_all` ベース、Alembic 未導入)。

---

## 5. アーキテクチャ

### 5.1 コンポーネント図

```
┌─────────────────────────────────────────────────────────────────────┐
│ External CVE/Advisory Sources                                        │
│   NVD API / GitHub Advisory GraphQL / OSV REST / VulnerableMCP HTML  │
└──────────┬──────────────────────────────────────────────────────────┘
           │ pull (cron 1〜2h)
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Collector (src/collector/)                                           │
│   nvd.py / github_advisory.py / osv.py / vulnerable_mcp.py / main.py │
└──────────┬──────────────────────────────────────────────────────────┘
           │ INSERT vulnerabilities
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ SQLite (data/security.db)                                            │
│   vulnerabilities / components / scan_results / audit_logs / tool_pins│
└──┬───────────────────────────────────────────────────────────┬──────┘
   │                                                            │
   │ inventory_match                                            │ read
   ▼                                                            │
┌─────────────────────────────────────────────────────────────┐ │
│ Analyzer (src/analyzer/)                                    │ │
│   inventory_match.py / scorer.py / llm_analyst.py / main.py │ │
│   - inventory.yaml → components ↔ vulnerabilities          │ │
│   - LLM (Claude / Vertex Gemini) で attack_summary 等生成   │ │
└──┬──────────────────────────────────────────────────────────┘ │
   │ INSERT 通知対象                                              │
   ▼                                                            │
┌─────────────────────────────────────────────────────────────┐ │
│ Notifier (src/notifier/)                                    │ │
│   slack.py / line.py / email_notifier.py                    │ │
│   formatter.py / digest.py                                  │ │
└─────────────────────────────────────────────────────────────┘ │
                                                                 │
                                                                 │
   ┌─────────────────────────────────────────────────────────────┴───────┐
   │                                                                      │
   │  Agent (e.g. kanie-lab / driving-license-bot)                       │
   │     │                                                                │
   │     │  .mcp.json で proxy:8080 を指す                                │
   │     ▼                                                                │
   │  ┌─────────────────────────────────────────────────────────┐        │
   │  │ MCP Proxy (src/proxy/server.py + uvicorn)               │        │
   │  │   inbound.py → injection.py / dlp.py / rate_limiter.py  │        │
   │  │              → tool_pinning.py / destination.py         │        │
   │  │   outbound.py ──────────▶  Real MCP Server              │        │
   │  │   passive: log only / active: block                     │        │
   │  └────────┬────────────────────────────────────────────────┘        │
   │           │ INSERT audit_logs / tool_pins                            │
   │           ▼                                                          │
   │  SQLite (audit_logs)                                                 │
   └──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ Dashboard (src/dashboard/app.py + FastAPI + Jinja2)                  │
│   :8000 で SQLite を直接読み、脆弱性 / inventory / audit を表示       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ CI Security Scan (.github/workflows/pr-security.yml)                 │
│   gitleaks (commit range) + bandit (changed .py、medium+)            │
│   SARIF を artifact として 7 日保管                                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 主要モジュール

| モジュール | 役割 | 主要ファイル | 規模 |
|---|---|---|---|
| `collector/` | 4 ソースから CVE/Advisory 取得 | `nvd.py` / `github_advisory.py` / `osv.py` / `vulnerable_mcp.py` / `main.py` | ~600 行 |
| `analyzer/` | inventory matching + LLM 分析 | `inventory_match.py` / `scorer.py` / `llm_analyst.py` / `main.py` | ~500 行 |
| `notifier/` | Slack / LINE / Email + digest | `slack.py` / `line.py` / `email_notifier.py` / `formatter.py` / `digest.py` | ~474 行 |
| `proxy/` | MCP プロキシ (Tool Pinning / DLP / Rate / Injection / Destination) | `server.py` (667 行) / `dlp.py` / `injection.py` / `rate_limiter.py` / `tool_pinning.py` / `destination.py` / `inbound.py` / `outbound.py` / `mcp_client.py` | ~1,975 行 |
| `dashboard/` | FastAPI + Jinja2 テンプレ | `app.py` | ~中規模 |
| `db/` | SQLAlchemy models + migrations | `models.py` (159 行) / `migrations.py` | ~200 行 |
| `config.py` | YAML / .env のローダ (pydantic-settings) | `config.py` | 1 ファイル |

### 5.3 外部連携

| 連携先 | 用途 | 認証方式 |
|---|---|---|
| NVD (`services.nvd.nist.gov/rest/json/cves/2.0`) | CVE 取得 | API key 任意 (`NVD_API_KEY`) |
| GitHub Advisory (`api.github.com/advisories`) | GHSA 取得 | `GITHUB_TOKEN` (rate limit 緩和) |
| OSV (`api.osv.dev`) | npm/PyPI/Go advisory | 認証不要 |
| VulnerableMCP (`vulnerablemcp.info`) | MCP 特化 advisory | 認証不要 (HTML scrape) |
| Anthropic API | LLM 分析 (Claude) | `ANTHROPIC_API_KEY` |
| Vertex AI (Gemini) | LLM 分析 (代替) | ADC (`gcloud auth application-default login`) |
| LINE Messaging API | Bot push | `LINE_CHANNEL_SECRET` + `LINE_CHANNEL_ACCESS_TOKEN` |
| Slack | Webhook 投稿 | `SLACK_WEBHOOK_URL` |
| SMTP | Email 送信 | `SMTP_*` env |
| Snyk (任意) | MCP / Skill scan | `SNYK_TOKEN` (Phase 4 計画中) |
| Promptfoo | Red team | Anthropic API key |

---

## 6. 開発フェーズ / Roadmap

| Phase | 名前 | スコープ | 状態 |
|---|---|---|---|
| Phase 1 | 基盤 | NVD/GHSA/OSV collector + inventory matching + Slack/Email 通知 + Dashboard | ✅ 完了 |
| Phase 2 | 拡張 | VulnerableMCP collector + LLM 分析 + LINE 通知 + Daily digest + cron 自動化 | ✅ 完了 |
| Phase 3 | MCP Proxy | Tool Pinning / DLP / Rate Limit / Injection / Destination filter / Audit Log / Red team | ✅ 完了 |
| Phase 4 | CI 統合 | gitleaks + bandit を PR で gating、pip-audit / snyk は計画中 | 🔶 部分実装 |
| Phase 5+ | Cloud デプロイ | Cloud Run / GKE 上で proxy + dashboard を運用、Cloud SQL に移行 | ⬜ 未着手 |

---

## 7. 設計判断ログ (ADR-lite)

| 日付 | 判断 | 理由 | 詳細 |
|---|---|---|---|
| 2025 初期 | SQLite を採用 (PostgreSQL は Phase 5+) | 個人運用 + 単一プロセス前提、運用コスト 0 | — |
| 2025 初期 | Alembic ではなく `Base.metadata.create_all` | スキーマ変更が稀、migration の運用コストを避ける | `src/db/migrations.py` |
| 2025 初期 | SARIF 出力を artifact として保存 | GitHub Code Scanning は private repo で有料、簡易な閲覧に留める | `.github/workflows/pr-security.yml` |
| 2025 初期 | LLM 分析対象は inventory_match=true のみ | raw CVE 全件に LLM を当てるとコスト過多、shotgun 通知も避けたい | `src/analyzer/main.py` |
| 2025 中盤 | MCP Proxy は HTTP transport 専用 | stdio transport は intercept 不可。MCP server 側で HTTP モードに切替 | `src/proxy/server.py` |
| 2025 中盤 | passive / active モードを明示的に切替 | 導入直後は false positive 過多になりがち、1〜2 週間 passive で calibrate | `config/scan.yaml` `gateway.mode` |
| 2025 中盤 | Tool Pinning は fingerprint-only (動作変更検知) | tool definition の hash を固定、変わったら警告 (rug-pull) | `src/proxy/tool_pinning.py` |
| 2026-04 | LINE Notify を廃止し Messaging API に移行 | LINE Notify は 2025-03-31 サービス終了 | `src/notifier/line.py` |
| 2026-04 | LLM provider に Vertex Gemini を選択肢追加 | GCP IAM で統制、Anthropic API 直叩きより監査しやすい | `src/analyzer/llm_analyst.py` |
| 2026-04 | DLP は regex ベース (ML 分類器は不採用) | latency 50ms 以内の制約、false positive は手動で pattern 追加 | `src/proxy/dlp.py` |
| 2026-04 | Rate Limit は sliding window + circuit breaker 併用 | スパイク時のサーバ過負荷防止 + abusive client 自動遮断 | `src/proxy/rate_limiter.py` |
| 2026-04 | Audit Log は SQLite + JSONL の二重書き | SQLite は dashboard 用、JSONL は外部 SIEM 取り込み用 | `src/proxy/server.py` |
| 2026-04 | bandit severity フィルタは medium+ から開始 | 既存コードに low が大量、まず medium+ を 0 件にしてから ratchet | `.github/workflows/pr-security.yml` |
| 2026-04 | gitleaks allowlist は narrow `paths` 優先 | broad regex にすると本物の secret も見逃す | `.gitleaks.toml` |
| 2026-04 | Snyk Agent Scan は CI 統合保留 | 有料 SNYK_TOKEN 要、ローカル script で代替 | `scripts/scan-mcp.sh` / `scan-skills.sh` |

---

## 8. 運用

### 8.1 デプロイ

現状ローカル運用のみ。Cloud デプロイ (Phase 5+) は `infra/Dockerfile.proxy` に proxy 用 Dockerfile が雛形として存在。

```bash
# ローカル各コンポーネント (詳細は README §0.4 / §1)
make dashboard      # :8000
make proxy          # :8080 (MCP_TARGET_URL=... を指定)
make collector      # 単発 CVE 取得
make analyzer       # 単発分析 + 通知
make digest         # daily digest
make cron           # cron 自動化セットアップ
```

### 8.2 バックアップ / リストア

- `data/security.db` (SQLite) を任意のタイミングでコピー
- `logs/*.jsonl` は append-only、運用者が定期削除
- inventory / scan / notification の YAML は git 管理 (バックアップ不要)

### 8.3 モニタリング

- **Dashboard** (`localhost:8000`): 脆弱性件数 / inventory match / audit log を表示
- **Cron 実行ログ**: `logs/cron.log` (setup-cron.sh が `crontab -e` に追記する)
- **MCP Proxy**: stdout に `structlog` で出力、blocked decision は WARN+
- **GitHub Actions**: `pr-security.yml` の SARIF artifact (7 日保管)

### 8.4 onboarding 手順 (新規エージェント追加)

1. `config/inventory.yaml` に MCP server / npm / pip パッケージを追加
2. `config/scan.yaml` の `targets.{mcp_configs,skills_directories,source_directories}` に追加
3. (任意) MCP Proxy を経由する場合は agent 側 `.mcp.json` の URL を `http://localhost:8080` に変更
4. `make collector && make analyzer` で疎通確認
5. Dashboard で inventory に表示されることを確認

---

## 9. セキュリティ・プライバシー

### 9.1 データ分類

| 種類 | 例 | 取扱い |
|---|---|---|
| PII | tool 呼出パラメータ (user 入力含むケース) | DLP で API key / credential / 個人情報をマスクして audit_logs に保存 |
| 機密 | `LINE_CHANNEL_ACCESS_TOKEN` / `ANTHROPIC_API_KEY` / `SNYK_TOKEN` | `config/.env` (gitignore) のみ。Cloud 移行時は Secret Manager |
| 公開可 | `inventory.yaml` (パッケージ名のみ) / `scan.yaml` / `notification.yaml` | git 管理 |

### 9.2 認証・認可

- **Dashboard**: 認証なし (localhost 前提)。公開する場合は IAP / Basic Auth を前段に置く
- **MCP Proxy**: 認証なし (localhost 前提)。Cloud 展開時は agent から SA トークン or mTLS 想定
- **CVE source API**: 各社 API key を `config/.env` に保管

### 9.3 既知のリスク・残課題

| ID | 内容 | 対策状況 |
|---|---|---|
| R1 | MCP Proxy の DLP は regex ベースで false negative がある | Phase 5 で ML 分類器検討 |
| R2 | Tool Pinning は initial fingerprint を信用する TOFU 方式 | 初回 onboarding 時の検証は手動 |
| R3 | Audit Log の retention 削除は手動 | Phase 4 で cron 化 |
| R4 | Cloud 展開時の認証 (Dashboard / Proxy) 未設計 | Phase 5+ |
| R5 | LLM 分析時の prompt injection 耐性 | CVE description は信頼するが summary に含める範囲は限定 |
| R6 | snyk / pip-audit が未統合 | Phase 4 計画中 (`README.md` 末尾の TODO) |

---

## 10. テスト戦略

| レイヤ | 対象 | カバレッジ目標 |
|---|---|---|
| Unit | DLP regex / scorer / inventory_match / formatter | 90% |
| Integration | collector → DB → analyzer → notifier の通し | 80% |
| E2E (proxy) | inbound → DLP/Rate/Pinning → outbound → audit_log | 主要シナリオ |
| Red team | Promptfoo シナリオ (RBAC / Prompt Injection / DoS) | 主要 OWASP ASI |

テストファイル構成 (23 ファイル):

```
tests/
├── analyzer/        # inventory_match / scorer / llm_analyst
├── collector/       # nvd / github_advisory / osv / vulnerable_mcp
├── db/              # models / migrations
├── notifier/        # slack / line / email / digest
├── proxy/           # dlp / rate_limiter / tool_pinning / injection / destination / server
├── scripts/         # scan-mcp / scan-skills の smoke
└── conftest.py
```

CI: `.github/workflows/pr-tests.yml` の `test-security-platform` で実行。

---

## 11. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / 主要コマンド / 各レイヤー適用手順
- [`../config/inventory.yaml`](../config/inventory.yaml) — 監視対象の MCP server / npm / pip パッケージ
- [`../config/scan.yaml`](../config/scan.yaml) — scan target / NVD keywords / proxy gateway 設定
- [`../config/notification.yaml`](../config/notification.yaml) — 通知 channel / severity しきい値
- [`../scripts/`](../scripts/) — 各種シェルスクリプト (scan-mcp / scan-skills / setup-cron / redteam)
- [`../../docs/PROPOSALS/`](../../docs/PROPOSALS/) — モノレポ共通の per-feature proposal / ADR
- [`../../docs/MIGRATION_PLAN.md`](../../docs/MIGRATION_PLAN.md) — ドキュメント refactoring 全体計画

---

## 12. 用語集

| 用語 | 意味 |
|---|---|
| MCP | Model Context Protocol。Claude / 他 LLM が外部 tool を呼び出すための標準プロトコル |
| CVE | Common Vulnerabilities and Exposures。脆弱性の標準 ID |
| GHSA | GitHub Security Advisory ID |
| OSV | Open Source Vulnerability database (Google) |
| OWASP ASI | OWASP AI Security & Privacy Initiative の Top 10 (ASI01〜ASI10) |
| OWASP LLM Top 10 | OWASP の LLM アプリケーション向け Top 10 |
| Tool Pinning | MCP tool の definition に fingerprint (sha256) を取り、変更を検知する手法 |
| Rug-pull 攻撃 | 信頼を得た MCP server が後から悪意ある tool 定義を追加する攻撃 |
| DLP | Data Loss Prevention。tool 呼出パラメータから機密情報を検出 |
| Prompt Injection | LLM への入力に攻撃指示を埋め込み、想定外の動作を誘発する攻撃 |
| Indirect Prompt Injection | tool 経由で取得したコンテンツに injection を仕込む攻撃 |
| passive mode | 違反を log のみ、トラフィックは通す (calibration 期間用) |
| active mode | 違反をブロックし即時 alert (本番運用) |
| Promptfoo | LLM の red team / 評価ツール |
| inventory match | CVE の affected component が `inventory.yaml` の登録パッケージに合致する状態 |
| sliding window rate limit | 直近 N 秒の呼出数で制限 (token bucket と異なり経過時間で減算) |
| circuit breaker | 連続失敗で一時的に呼出を遮断するパターン |
