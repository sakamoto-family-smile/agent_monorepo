# PROPOSAL-0006: EDINET 統合による株価分析の深化

| | |
|---|---|
| **Status** | Draft |
| **Author** | @kurama554101 |
| **Created** | 2026-05-22 |
| **Updated** | 2026-05-22 |
| **Target** | stock-analysis-agent (主) + 共有 `edinet-client` 新規パッケージ |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

金融庁が運営する **EDINET (Electronic Disclosure for Investors' NETwork)** の API v2 を統合し、 stock-analysis-agent が **有価証券報告書 / 四半期報告書 / 大量保有報告書** 等の法定開示書類を分析に活用できるようにする。 yfinance ベースの市場データ + Brave Search ニュースに加えて **一次情報 (監査済 / 構造化済)** を組み合わせ、 「セグメント別売上推移」 「中期経営計画」 「リスク要因の自然文抽出」 等の深い分析を提供する。

実装は **共有 path-dep パッケージ `edinet-client/`** として monorepo の既存パターン (`llm-client` / `analytics-platform` / `fujisawa-platform`) に揃え、 将来的に MCP server 化 / 他エージェント (lifeplanner-agent 等) でも再利用できる形にする。

---

## 2. Motivation

### 現状の課題

- stock-analysis-agent は yfinance + Brave Search に依存しており、 **財務 3 表の詳細** (B/S / P/L / C/F)、 **セグメント別売上 / 利益**、 **中期経営計画 / リスク要因の自然文**、 **大量保有報告 (機関投資家動向)** 等の一次情報が取得できない
- LLM が分析する根拠データが市場データ + ニュースに偏り、 「経営戦略の評価」 「事業ポートフォリオ変化の評価」 等の本質的な分析ができない
- 米国株 (SEC EDGAR) は別途検討要 (本提案では Out of Scope)

### 放置するとどうなるか

- 分析レポートが 「価格テクニカル + 直近ニュース」 ベースに留まり、 中期投資判断に必要な深さに到達しない
- ユーザーから 「セグメント別の業績を見て」 「中計の前提を踏まえて」 等の要望が出てきた際に対応できない
- 競合 (Bloomberg / 日経テレコン / Refinitiv) との差別化が困難 (月数万円の有料サービスでしか得られない情報を、 無料 API で代替する機会を逃す)

### 2.1 Goals

- [ ] `edinet-client/` package を新規作成し、 monorepo 内の他エージェントから path dep で利用可能にする
- [ ] stock-analysis-agent が **指定銘柄の最新有価証券報告書 (年次)** を取得 → LLM に投入できる
- [ ] stock-analysis-agent が **直近 4 四半期報告書** を取得 → LLM に投入できる
- [ ] EDINET 文書本体は **GCS (or local file) に cache** され、 同一文書の再取得を回避する (有報は immutable、 TTL ∞)
- [ ] 日次 batch で EDINET 文書 **INDEX** を Cloud SQL に投入し、 銘柄別の最新書類 ID を即座に lookup できる
- [ ] **ticker (`7203.T`) → EDINET コード (`E02144`) のマッピング** が自動化される (EDINET 公式 `Edinetcode.csv` から構築)
- [ ] テストが LLM / 実 API を呼ばずに通る (mock-friendly な Protocol 抽象)

### 2.2 Non-Goals

- **米国株 (SEC EDGAR)** との統合 (将来の別 proposal で検討)
- **XBRL parser での構造化数値抽出** (Phase 2 で対応、 Phase 1 は PDF / テキストを LLM に直接投入する MVP)
- **大量保有報告 / 公開買付の subscribe** (Phase 3+)
- 既存 `stock-analysis-agent` の Phase A (投資信託レコメンド) / Phase B (LINE Bot) との統合 (Phase 3+ で検討)
- MCP server 化 (将来オプション、 Phase 4+。 本 proposal では client lib として完結させる)
- 自前で書類を画面表示する UI (Claude / LINE 出力に委ねる)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 ストーリー 1: セグメント別売上の評価

> 個人投資家の田中さんが LINE で 「キオクシア (285A) の最新業績、 データセンター向け売上の推移は？」 と送ると、 stock-analysis-agent は EDINET API 経由で **キオクシアの最新有価証券報告書** を取得 → 「セグメント別売上」 のページを Claude に渡して 「データセンター向け SSD 売上が前年比 +70%、 売上構成比は 60% に拡大」 と回答。 出典として EDINET 書類 ID と提出日を明示。

#### 3.1.2 ストーリー 2: 中期経営計画 / リスク要因の引用

> ユーザーが 「JTC 7370 の事業リスクを評価して」 と送ると、 agent は最新有報の 「事業等のリスク」 セクションを Claude に渡し、 「為替変動 / 顧客集中 / 半導体サイクル」 等の自然文を要約して提示。 「会社が自身でどう認識しているか」 という質の高い情報源。

#### 3.1.3 ストーリー 3: 大量保有報告 (Phase 3+)

> 「直近のキオクシアの大株主動向は？」 → 大量保有報告書の届出履歴から Bain Capital / 機関投資家の保有比率変化を抽出して提示。 **Phase 1 のスコープ外、 将来拡張**。

### 3.2 Notes / Constraints / Caveats

- **EDINET API は API key 必須** (2024 年〜、 無料登録)
- **対象は日本上場企業のみ** (TSE / 名証 / 札証 / 福証)
- 1 社の有価証券報告書は PDF で 50-200 ページ、 XBRL で **5-50 MB**
- **全社全件保存は非現実的** (4,000 社 × 5 件/年 = 1-2 TB/年)
- 書類は **immutable** (一度提出されたら変更されない) → cache TTL は ∞ で OK
- 文書 INDEX (メタデータ) は **1 日 数 KB** で軽量、 日次 batch で取得可能
- 提出タイミングは **期末 + 45 日 (四半期)** / **+ 3 ヶ月 (有報)** で、 リアルタイム性は決算短信より遅い

### 3.3 Risks and Mitigations

| リスク | 影響 | 緩和策 |
|---|---|---|
| **EDINET API rate limit** | 大量 fetch で 429 | INDEX は daily batch (1 回/日 数 MB)、 本体はオンデマンド + cache。 並列度を絞る (1 リクエスト/秒) |
| **API 仕様変更** | client が壊れる | Protocol 抽象 + 実装の差し替え可能設計。 schema 変更時は単体テストで早期検知 |
| **XBRL parsing の沼** | Phase 2 で時間溶ける | Phase 1 は PDF / テキスト直 (XBRL skip)、 LLM に解析を委譲 |
| **米国株サポート不足** | 米国株分析の質は変わらず | Non-Goals 明示。 将来 SEC EDGAR を別 proposal で |
| **storage 肥大** | GCS コスト増 | TTL∞ だが 1 社あたりの cache 量を制限 (最新 + 直近 4 四半期のみ)、 アクセスされない書類は LRU で削除可 |
| **書類サイズが LLM コンテキストを圧迫** | Claude/Gemini 入力上限超過 | PDF はページ単位で分割 → 関連セクション抽出後に LLM 投入、 全文投入はしない |
| **EDINET コード解決の不整合** | 銘柄取り違え | `Edinetcode.csv` から構築 + ticker (`xxxx.T`) と EDINET code の 2 つで突合チェック |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
┌───────────────────────────────────────────────────┐
│ stock-analysis-agent (FastAPI)                    │
│                                                   │
│  orchestrator.py                                  │
│    └─ run_analysis()                              │
│        ├─ yfinance (価格 / テクニカル)            │
│        ├─ Brave Search (ニュース / センチメント)  │
│        └─ EDINET (財務 / 中計 / リスク要因)       │
│           └─ from edinet_client import …          │
└───────┬───────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│ edinet-client/ (path dep, 新規) │
│  ┌─────────────┐                │
│  │ EdinetClient│ HTTPX async    │
│  └──────┬──────┘                │
│  ┌──────▼──────┐                │
│  │ DocumentList│ INDEX get      │
│  │ Document    │ ZIP download   │
│  │ CodeResolver│ ticker→EDINET  │
│  └──────┬──────┘                │
│  ┌──────▼──────┐                │
│  │ Cache       │ Protocol       │
│  │  - Local    │                │
│  │  - GCS      │                │
│  └─────────────┘                │
└──────────┬──────────────────────┘
           │
           ▼ HTTPS (EDINET API key)
┌─────────────────────────────────┐
│ EDINET (金融庁)                  │
│  api/v2/documents.json           │
│  api/v2/documents/<id>?type=2    │
└──────────────────────────────────┘

[Daily batch (Cloud Run Jobs、 後追い)]
   Cloud Scheduler (毎日 02:00 JST) ──▶ Cloud Run Job (edinet_index_etl)
                          ├─ 直近 7 日分 (rolling window) の文書 INDEX を fetch
                          │   - 1 日ずつ api/v2/documents.json?date=YYYY-MM-DD&type=2 を叩く
                          │   - type=2 で securities_code 等のフルメタデータ取得
                          ├─ 全書類タイプ (有報・四半期・大量保有 等) を取得 (絞らず保存)
                          └─ Cloud SQL `edinet_documents` に upsert (PK=document_id)
                              - 新規書類: INSERT
                              - 既存書類: status 系フィールドのみ UPDATE
                                (取下げ / 開示停止が遅れて反映されるため 7 日窓 で捕捉)

[One-shot backfill (初回 / 過去データ投入)]
   gcloud run jobs execute ... -- args=edinet_backfill --from=YYYY-MM-DD --to=YYYY-MM-DD
   - デプロイ直後の初期 backfill (過去 90 日 ~ 1 年) に利用
   - 通常運用後は再実行しない
```

### 4.2 データモデル

#### `edinet-client` の公開型 (Pydantic)

```python
class DocumentType(StrEnum):
    ANNUAL_REPORT = "120"        # 有価証券報告書
    QUARTERLY_REPORT = "140"     # 四半期報告書
    SEMI_ANNUAL_REPORT = "160"   # 半期報告書
    EXTRAORDINARY_REPORT = "180" # 臨時報告書
    MAJOR_HOLDING = "350"        # 大量保有報告書
    TENDER_OFFER = "490"         # 公開買付届出書
    # (一部抜粋、 EDINET 仕様コードに従う)


class DocumentMetadata(BaseModel):
    document_id: str          # docID (例: "S100ABC1")、 immutable
    edinet_code: str          # 提出者 EDINET code (例: "E02144")
    securities_code: str | None  # 4 桁証券コード (例: "7203")
    submitter_name: str       # 提出者名 (例: "トヨタ自動車株式会社")
    document_type: DocumentType
    submit_date: date         # 提出日
    period_end: date | None   # 期末日
    description: str          # 書類概要
    # ── 以下、 status 系 (rolling window で upsert される可能性) ──
    withdrawal_status: int    # 0=有効、 1=取下げ
    disclosure_status: int    # 0=開示中、 1=開示停止、 2=公開停止
    doc_info_edit_status: int # 0=未編集、 1=編集済 (件名 / 概要が訂正されている)
    xbrl_flag: bool           # XBRL 有無
    pdf_flag: bool            # PDF 有無
    attach_doc_flag: bool     # 添付書類有無


class DocumentBody(BaseModel):
    """download() の結果。 PDF は bytes、 XBRL は zip bytes。"""
    document_id: str
    content_type: Literal["pdf", "xbrl_zip"]
    bytes: bytes
    fetched_at: datetime
```

#### Cloud SQL スキーマ (`edinet_documents` テーブル)

```sql
CREATE TABLE edinet_documents (
    document_id            TEXT PRIMARY KEY,
    edinet_code            TEXT NOT NULL,
    securities_code        TEXT,                   -- 4 桁証券コード (nullable)
    submitter_name         TEXT NOT NULL,
    document_type          TEXT NOT NULL,          -- DocumentType 値
    submit_date            DATE NOT NULL,
    period_end             DATE,
    description            TEXT,
    -- ── status 系 (rolling 7 日窓 upsert で最新化される) ──
    withdrawal_status      SMALLINT NOT NULL DEFAULT 0,  -- 0=有効, 1=取下げ
    disclosure_status      SMALLINT NOT NULL DEFAULT 0,  -- 0=開示中, 1=開示停止, 2=公開停止
    doc_info_edit_status   SMALLINT NOT NULL DEFAULT 0,
    xbrl_flag              BOOLEAN NOT NULL DEFAULT FALSE,
    pdf_flag               BOOLEAN NOT NULL DEFAULT FALSE,
    attach_doc_flag        BOOLEAN NOT NULL DEFAULT FALSE,
    -- ── cache 状態 ──
    cache_uri              TEXT,                   -- gs://bucket/path or file:// (NULL なら未 cache)
    cached_at              TIMESTAMPTZ,
    -- ── upsert 監査用 ──
    first_seen_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_index_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX edinet_documents_securities_code_submit_date_idx
    ON edinet_documents (securities_code, submit_date DESC);
CREATE INDEX edinet_documents_edinet_code_submit_date_idx
    ON edinet_documents (edinet_code, submit_date DESC);
CREATE INDEX edinet_documents_type_submit_date_idx
    ON edinet_documents (document_type, submit_date DESC);
-- 取下げ・開示停止された書類を素早く絞り込むため
CREATE INDEX edinet_documents_status_idx
    ON edinet_documents (withdrawal_status, disclosure_status)
    WHERE withdrawal_status <> 0 OR disclosure_status <> 0;
```

書類本体 (PDF / XBRL) は **immutable** だが、 status 系フィールド (取下げ / 開示停止 / 編集) は提出後に変わる可能性がある。 そのため:
- INDEX 取得は **rolling 7 日窓で upsert** (毎日同じ日を 7 回 fetch、 status の遅延変更を 1 週間以内に反映)
- 書類本体の cache TTL は **∞** (immutable のため再取得不要)
- 利用側 (orchestrator) は `withdrawal_status = 0 AND disclosure_status = 0` の書類のみを採用

### 4.3 API

#### `edinet-client` (Python 公開 API)

```python
from edinet_client import EdinetClient, DocumentType, LocalCache, GcsCache

client = EdinetClient(
    api_key=settings.edinet_api_key,
    cache=LocalCache(root="./data/edinet"),     # or GcsCache(bucket="...")
    user_agent="stock-analysis-agent/0.1 (https://example.com)",
)

# 1) 文書 INDEX 取得 (daily batch 用)
docs = await client.list_documents(date(2026, 5, 22))
# → list[DocumentMetadata]

# 2) ticker → EDINET コード解決
edinet_code = await client.resolve_edinet_code("7203.T")  # → "E02144"

# 3) ある会社の最新有報を取得
latest = await client.get_latest_filing(
    edinet_code="E02144",
    document_type=DocumentType.ANNUAL_REPORT,
)
# → DocumentMetadata

# 4) 本体取得 (cache 経由)
body = await client.download(latest.document_id, content_type="pdf")
# → DocumentBody (bytes 含む)。 cache hit なら HTTP は飛ばない
```

#### stock-analysis-agent 側の利用 (Phase 1 MVP)

```python
# app/agents/edinet_collector.py (新規、 ~150 LoC 想定)
async def fetch_latest_filings(
    ticker: str, *, n_quarters: int = 4
) -> list[DocumentBody]:
    code = await edinet_client.resolve_edinet_code(ticker)
    annual = await edinet_client.get_latest_filing(code, DocumentType.ANNUAL_REPORT)
    quarterlies = await edinet_client.get_recent_filings(
        code, DocumentType.QUARTERLY_REPORT, limit=n_quarters,
    )
    docs = [annual, *quarterlies] if annual else quarterlies
    return [await edinet_client.download(d.document_id, content_type="pdf") for d in docs]
```

orchestrator から呼び出して、 PDF bytes を Claude Agent SDK の attachment / Read tool として渡す。

### 4.4 主要モジュール

```
edinet-client/
├── pyproject.toml             # llm-client / analytics-platform と同パターン
├── README.md
├── edinet_client/
│   ├── __init__.py            # public API: EdinetClient, types
│   ├── client.py              # HTTP client (httpx async + retry)
│   ├── types.py               # Pydantic models (Document, DocumentList, etc.)
│   ├── code_resolver.py       # ticker → EDINET code mapping (Edinetcode.csv 同梱 or DB)
│   ├── cache.py               # Cache Protocol + LocalCache / GcsCache 実装
│   └── _xbrl_parser.py        # (Phase 2 で追加、 Phase 1 は空 or stub)
└── tests/
    ├── test_client.py         # respx で API mock
    ├── test_code_resolver.py
    ├── test_cache.py
    └── fixtures/
        ├── documents_index_sample.json
        └── Edinetcode_sample.csv

stock-analysis-agent/
├── app/agents/
│   └── edinet_collector.py    # 新規、 edinet-client を呼ぶ薄い層
├── tests/
│   └── test_edinet_collector.py
└── (orchestrator.py に EDINET 経路を組み込み)
```

Daily batch (後追い、 別 PR):

```
edinet-index-etl/             # or stock-analysis-agent/app/batch/edinet_index.py
└── 毎日 02:00 JST に Cloud Scheduler → Cloud Run Job →
    昨日の document INDEX を fetch → Cloud SQL (or SQLite) に upsert
```

### 4.5 Test Plan

#### Unit Tests
- `edinet_client.client`: respx で `/api/v2/documents.json` `/api/v2/documents/{id}` を mock し、 INDEX 取得 / 本体 download を検証
- `edinet_client.code_resolver`: 同梱の `Edinetcode_sample.csv` (10 行程度) でマッピング動作を検証
- `edinet_client.cache`: LocalCache の put / get、 TTL∞ の挙動、 GcsCache は moto / fake で
- `stock-analysis-agent.edinet_collector`: edinet_client を mock して orchestrator 経路を検証

#### Integration Tests (任意)
- `pytest.mark.integration` 付きで実 EDINET API を叩く smoke test (CI では skip、 環境変数 `EDINET_API_KEY` 有りで実行)
- 1 銘柄 (例 7203 トヨタ) の最新有報を取得 → PDF size > 0 確認

### 4.6 Migration / Rollback

- **Migration**: 既存 stock-analysis-agent には影響しない (新規 collector を opt-in で組み込み)
- **Rollback**: feature flag `EDINET_ENABLED=false` で edinet_collector の呼出 を skip。 orchestrator は EDINET なしでも完結する設計
- **既存ユーザー影響**: なし (新機能のみ)

### 4.7 Feature Enablement

| env | 既定 | 用途 |
|---|---|---|
| `EDINET_ENABLED` | `false` | EDINET 経路を有効化 (Phase 1 配備時に `true` に切替) |
| `EDINET_API_KEY` | (未設定) | EDINET API v2 のキー |
| `EDINET_CACHE_BACKEND` | `local` | `local` / `gcs` |
| `EDINET_CACHE_ROOT` | `./data/edinet` | LocalCache のルート |
| `EDINET_CACHE_GCS_BUCKET` | (未設定) | GcsCache のバケット名 |
| `EDINET_HTTP_QPS` | `1.0` | EDINET API への秒間リクエスト上限 |
| `EDINET_DAILY_WINDOW_DAYS` | `7` | daily batch の rolling window 日数 (status 系の遅延変更を捕捉) |
| `EDINET_DOCUMENT_TYPES` | (空 = 全件) | 取得対象書類タイプの csv (空なら全件保存)。 絞る場合 `120,140,160` 等 |
| `EDINET_BATCH_SCHEDULE` | `0 2 * * *` (毎日 02:00 JST) | Cloud Scheduler cron |

---

## 5. Operational Concerns

### 5.1 Monitoring

- analytics-platform (既存) に `business_event(action=edinet_document_fetched)` を発行
- メトリクス: 「EDINET 取得 latency」 「cache hit rate」 「rate limit hit (429)」 「EDINET コード解決失敗率」
- 重要アラート (将来):
  - cache hit rate < 50% (storage 設計の見直し示唆)
  - 429 が 1 日 10 回以上発生 (QPS 設定見直し)

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| 429 Too Many Requests | `EDINET_HTTP_QPS` を下げる、 並列度を絞る |
| ticker → EDINET コード解決失敗 | `Edinetcode.csv` が古い → 更新コマンドを叩く |
| GcsCache に書けない | SA に `roles/storage.objectAdmin` が付いているか確認 |
| 文書 ID が見つからない | INDEX batch が回っていないか、 銘柄が EDINET 対象外 (海外 / OTC) |

### 5.3 Dependencies

- **新規 (`edinet-client`)**:
  - `httpx` (HTTP client)
  - `pydantic`
  - `tenacity` (retry)
  - **optional**: `google-cloud-storage` (GcsCache 用、 `[gcs]` extra)
  - **optional (Phase 2)**: `python-xbrl` or `arelle` (XBRL parser、 `[xbrl]` extra)
- **stock-analysis-agent 追加**:
  - `edinet-client` (path dep)

### 5.4 Non-Functional Requirements

#### 性能
- INDEX 取得: 1 日分 (数 MB JSON) を < 30 秒で取得
- 本体 download: 1 件 (PDF 50MB) を < 60 秒で取得 (cache miss 時)
- cache hit: < 10 ms (LocalCache) / < 200 ms (GcsCache)
- ticker → EDINET code: < 5 ms (in-memory dict)

#### コスト (月間想定)
- EDINET API: **無料** (登録のみ)
- GCS storage: 100 GB × ¥3/GB/月 ≈ **¥300/月** (cache 100 GB 想定、 用途次第で調整)
- Cloud Run Job (daily batch): 1 日 30 秒 × 月 30 回 × 1 vCPU = ¥0 級
- LLM 経由のトークン: 1 銘柄 1 分析あたり 50-150k tokens 追加 → Gemini 2.5 Flash 換算で月 ¥100-300/月想定 (利用量次第)

#### プライバシー / データ保持
- EDINET 書類は **公開情報** (個人情報なし)
- ユーザーがどの銘柄を分析したかは analytics-platform に記録 (既存)
- cache に保存する書類自体に PII は含まれない

#### キャパシティ
- 1 日の INDEX 取得: 数千件のメタデータ、 Cloud SQL `edinet_documents` テーブルで容易にハンドル
- 並列 download: 同時 5-10 件まで (rate limit 配慮)

---

## 6. Drawbacks

- **米国株が対象外** のため、 米国株分析には別途 SEC EDGAR 統合が必要 (将来 proposal)
- **XBRL parsing は Phase 2 以降** で、 Phase 1 では PDF をそのまま LLM に投入する。 LLM への入力サイズ (token) が増える分の API 課金は増加
- **書類提出のタイムラグ** (有報 = 期末 + 3 ヶ月) のため、 「直近の業績」 は決算短信 / 適時開示の方が早い。 EDINET 単独で完結しない (yfinance / Brave Search との併用前提)
- **monorepo に新規パッケージが 1 つ増える** (`edinet-client/`)。 管理対象が増える分だけ運用負荷が上がる

これらを踏まえても、 一次情報の取り込みによる分析の深化メリットが大きく、 個人投資家向け差別化の核となるため採用する価値あり。

---

## 7. Alternatives

### 案 A: Bloomberg / Refinitiv 等の有料データプロバイダ

- 圧倒的にデータが整理されているが、 月数万円〜の課金が必要
- 個人プロジェクトでは ROI 合わず却下

### 案 B: 株探 / 日経テレコン等のスクレイピング

- 規約違反リスクが高い (商用利用不可 / 自動アクセス禁止)
- 安定性も低い (HTML 構造変更で壊れる)
- 却下

### 案 C: EDINET API を MCP server として実装

- universal (Claude Desktop 等の MCP-compliant client から直接呼べる)
- ただし MCP server 構築 + 維持のコストが高く、 Phase 1 MVP では over-engineering
- 本 proposal では **client lib を先に作り、 MCP 化は将来オプション** として位置付ける (Phase 4+)

### 案 D: J-Quants API を併用

- 日本取引所グループ (JPX) の公式 API。 価格・財務指標を提供
- yfinance の代替候補だが、 「監査済有報の自然文」 は取れない → EDINET の代替にはならない
- 必要なら別 proposal で yfinance → J-Quants 移行を検討 (本 proposal の Out of Scope)

### 案 E: stock-analysis-agent 内に EDINET 連携を完結させる (`app/agents/edinet/`)

- 確かに最初は楽だが、 `lifeplanner-agent` 等で再利用したくなった際に refactor 必要
- monorepo の既存パターン (`llm-client` / `analytics-platform` / `fujisawa-platform`) に揃える方が長期的にコスト低
- 却下、 採用は **案 (本 proposal 本案) = `edinet-client/` 新規 path-dep package**

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-22 | Draft | 初稿 (本 PR) |
| 2026-05-23 | Draft 改訂 | レビュー反映: daily batch を「rolling 7 日窓 + upsert」 に明文化、 status 系フィールド (取下げ / 開示停止 / 編集) を `DocumentMetadata` + Cloud SQL schema に追加、 schedule を 02:00 JST に確定、 one-shot backfill コマンド追加 |

---

## Phase Roadmap

| Phase | 内容 | 工数 |
|---|---|---|
| **Phase 1a** | `edinet-client` 雛形 (HTTP client + types + tests、 cache は LocalCache のみ) | 半日 |
| **Phase 1b** | `code_resolver` (Edinetcode.csv からマッピング構築) | 半日 |
| **Phase 1c** | LocalCache 完成 + GcsCache 実装 | 半日 |
| **Phase 1d** | stock-analysis-agent の `edinet_collector` 追加、 orchestrator に EDINET 経路組み込み (PDF 直渡し) | 1 日 |
| **Phase 1e** | daily batch Cloud Run Job で INDEX (rolling 7 日窓) を Cloud SQL に upsert + 初回 backfill コマンド | 1 日 |
| **Phase 2** | XBRL parser 統合 (構造化数値取得) | 2-3 日 |
| **Phase 3** | 大量保有報告 / 公開買付の subscribe + LINE Bot 連携 | 別 PR |
| **Phase 4** | MCP server 化 (`edinet-mcp-server/`) | 別 PR |

Phase 1 合計: **3-4 日**程度。 本 proposal が approved 後、 順次 PR を切る。
