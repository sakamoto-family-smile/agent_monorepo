# fujisawa-platform

藤沢市 HP / PDF を一次ソースとする共通基盤ライブラリ。両エージェント
(`fujisawa-info-bot` / `fujisawa-hokatsu-agent`) が path dep で参照し、
**クロール / PDF 解析 / ベクトル検索 / 出典 Skill / 表記ゆれ吸収 / ETL** を一元提供する。

> **Status**: Phase 1 着手中 (本パッケージの雛形 + crawler + skills + DB schema)

設計詳細は [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) 参照。
本 README は「動かす / 取り込む」観点に絞る。

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージ管理 |
| Cloud SQL (Postgres) + pgvector | optional | 本番ベクトル検索を回す場合のみ |

### 0.2 セットアップ

```bash
cd agent_monorepo/fujisawa-platform

make install          # 基本依存のみ
make install-phase1   # Phase 1 (resolver extras 含む)
```

### 0.3 テスト・静的解析

```bash
make test             # pytest
make lint             # ruff check
make format           # ruff format + auto-fix
make check            # lint + test
```

### 0.4 consumer (LINE bot / 保活) からの利用

```toml
# 消費者エージェントの pyproject.toml
[project]
dependencies = ["fujisawa-platform"]

[tool.uv.sources]
fujisawa-platform = { path = "../fujisawa-platform" }
```

```python
# 消費者コード例
from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig, parse_sitemap
from fujisawa_platform.models import FreshnessMetadata
from fujisawa_platform.skills import get_skill

# polite な fetch
config = PoliteFetcherConfig(
    user_agent="my-app/0.1 (https://example.com/contact)",
    min_interval_sec=3.0,
)
async with PoliteFetcher(config) as fetcher:
    result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/sitemap.xml")
    if hasattr(result, "text"):
        entries = parse_sitemap(result.text.encode("utf-8"))
        print(f"Found {len(entries)} URLs in sitemap")

# Skill File を LLM プロンプトに動的注入
citation_rules = get_skill("citation_format")
freshness_rules = get_skill("freshness_disclaimer")
```

---

## 1. 主要モジュール (Phase 1 範囲)

| モジュール | 役割 | 状態 |
|---|---|---|
| `fujisawa_platform.crawler.polite_fetcher` | UA / interval / If-Modified-Since / 5xx retry を備えた HTTP fetcher | ✅ 実装済 |
| `fujisawa_platform.crawler.sitemap_loader` | sitemap.xml parser (1,100+ URL 対応) | ✅ 実装済 |
| `fujisawa_platform.models.common` | `FreshnessMetadata` (鮮度メタデータ) | ✅ 実装済 |
| `fujisawa_platform.skills` | 共通 Skill File 5 種 + `get_skill()` loader | ✅ 実装済 |
| `fujisawa_platform.db` | `init_schema.sql` + `get_init_schema_sql()` loader | ✅ 実装済 |

Phase 2 以降に追加予定 (proposal 0003 §4.4):
- `pdf_pipeline/` (Docling wrapper + hash 差分検知)
- `knowledge_base/` (pgvector + Vertex Embedding)
- `resolver/` (FacilityResolver、表記ゆれ吸収)
- `crawler/rss_poller.py` / `crawler/wayback.py`
- `etl/` (Cloud Run Jobs entrypoints)

---

## 2. 環境変数

Phase 1 では env なし。Phase 2 以降で以下を導入予定:

| 変数 | 既定 | 用途 |
|---|---|---|
| `FUJISAWA_PLATFORM_USER_AGENT` | (必須) | crawler の UA。連絡先 URL 含めること |
| `FUJISAWA_PLATFORM_DB_URL` | (必須) | Cloud SQL Postgres 接続 URL |
| `FUJISAWA_PLATFORM_ANALYTICS_ENABLED` | true | analytics-platform への計装 ON/OFF |

---

## 3. DB セットアップ (Phase 1 範囲)

`fujisawa_kb_db` を Cloud SQL (driving-license-bot 既存 instance) に追加する想定。

```bash
# Cloud SQL (gcloud sql)
gcloud sql databases create fujisawa_kb_db --instance=<existing-instance>

# psql で schema 適用
psql $FUJISAWA_PLATFORM_DB_URL -f fujisawa_platform/db/init_schema.sql
```

Python から SQL を取り出すこともできる:

```python
from fujisawa_platform.db import get_init_schema_sql
print(get_init_schema_sql())
```

詳細は proposal 0003 §4.3 / §4.5.3 (IAM ロール分離) 参照。

---

## 4. ETL ジョブ (Phase 2 以降)

proposal 0003 §4.5.4 の通り、Cloud Run Jobs として実装予定:

| Job | 頻度 | 状態 |
|---|---|---|
| `weekly_crawl_etl` | 週次 | ⏳ Phase 2 |
| `monthly_vacancy_etl` | 月次 22 日 | ⏳ Phase 2 |
| `monthly_stats_compute` | 月次 23 日 | ⏳ Phase 2 |
| `half_yearly_facility_etl` | 半年次 | ⏳ Phase 2 |
| `yearly_navi_etl` | 年次 | ⏳ Phase 2 |
| `biyearly_admission_etl` | 年 2 回 | ⏳ Phase 2 |
| `wayback_backfill` | 一度きり | ⏳ Phase 2 |

---

## 5. 関連ドキュメント

- [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — 設計提案
- [`../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../docs/PROPOSALS/0004-fujisawa-info-bot.md) — 利用先 1: 一般情報 LINE bot
- [`../docs/PROPOSALS/0005-fujisawa-hokatsu-agent.md`](../docs/PROPOSALS/0005-fujisawa-hokatsu-agent.md) — 利用先 2: 保活エージェント
- [`../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md`](../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md) — 事前調査結果
- [`fujisawa_platform/skills/`](fujisawa_platform/skills/) — 共通 SKILL.md 5 種
