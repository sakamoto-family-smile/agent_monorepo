import aiosqlite
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import config  # NOTE: `from config import settings` だと importlib.reload 後の
# 新 settings インスタンスを参照できず test isolation が壊れるので、 module
# 自体を import して `config.settings.db_path` で毎回 lookup する。

logger = logging.getLogger(__name__)


def _db_path() -> str:
    """`settings.db_path` を毎回 lookup する (test isolation 用)。

    モジュール ロード時に `DB_PATH = settings.db_path` を constant 化したり
    `from config import settings` で reference を捕まえると、 test fixture が
    `importlib.reload(config)` で settings を作り直しても古い値が使われて
    `sqlite3.OperationalError: no such table: ...` の test isolation 失敗を起こす。
    毎回 `config.settings.db_path` を読み直すことで回避。
    """
    return config.settings.db_path


async def init_db() -> None:
    """Initialize SQLite database with schema."""
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS ticker_dictionary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                ticker TEXT NOT NULL,
                aliases TEXT DEFAULT '[]',
                market TEXT DEFAULT 'unknown',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(company_name, ticker)
            );

            CREATE TABLE IF NOT EXISTS price_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                period TEXT NOT NULL,
                data TEXT NOT NULL,
                cached_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT NOT NULL,
                UNIQUE(ticker, period)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company_name TEXT,
                report_data TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                condition_data TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- proposal 0006 Phase 1e: EDINET 文書 INDEX
            -- daily batch (rolling 7 日窓) で upsert される。 document_id を PK
            -- とし、 status 系フィールドの遅延変更 (取下げ / 開示停止) を捕捉する。
            CREATE TABLE IF NOT EXISTS edinet_documents (
                document_id TEXT PRIMARY KEY,
                edinet_code TEXT NOT NULL,
                securities_code TEXT,
                submitter_name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                submit_date TEXT NOT NULL,        -- YYYY-MM-DD
                period_end TEXT,                   -- YYYY-MM-DD or NULL
                description TEXT DEFAULT '',
                withdrawal_status INTEGER NOT NULL DEFAULT 0,
                disclosure_status INTEGER NOT NULL DEFAULT 0,
                doc_info_edit_status INTEGER NOT NULL DEFAULT 0,
                xbrl_flag INTEGER NOT NULL DEFAULT 0,
                pdf_flag INTEGER NOT NULL DEFAULT 0,
                attach_doc_flag INTEGER NOT NULL DEFAULT 0,
                cache_uri TEXT,                    -- NULL なら未 cache
                cached_at TEXT,
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_index_refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ticker_dict_name ON ticker_dictionary(company_name);
            CREATE INDEX IF NOT EXISTS idx_price_cache_ticker ON price_cache(ticker, period);
            CREATE INDEX IF NOT EXISTS idx_reports_ticker ON reports(ticker);
            CREATE INDEX IF NOT EXISTS idx_edinet_docs_sec_code_date
                ON edinet_documents (securities_code, submit_date DESC);
            CREATE INDEX IF NOT EXISTS idx_edinet_docs_edinet_code_date
                ON edinet_documents (edinet_code, submit_date DESC);
            CREATE INDEX IF NOT EXISTS idx_edinet_docs_type_date
                ON edinet_documents (document_type, submit_date DESC);
        """)

        # Seed common Japanese/US stocks
        await _seed_ticker_dictionary(db)
        await db.commit()
    logger.info("Database initialized at %s", _db_path())


async def _seed_ticker_dictionary(db: aiosqlite.Connection) -> None:
    """Seed common tickers into dictionary."""
    stocks = [
        # Japanese stocks (TSE)
        ("トヨタ", "7203.T", ["toyota", "トヨタ自動車", "Toyota Motor"], "TSE"),
        ("ソニー", "6758.T", ["sony", "ソニーグループ", "Sony Group"], "TSE"),
        ("ソフトバンク", "9984.T", ["softbank", "ソフトバンクグループ"], "TSE"),
        ("任天堂", "7974.T", ["nintendo", "Nintendo"], "TSE"),
        ("ホンダ", "7267.T", ["honda", "本田技研工業", "Honda Motor"], "TSE"),
        ("三菱UFJ", "8306.T", ["mufg", "三菱UFJフィナンシャル"], "TSE"),
        ("キーエンス", "6861.T", ["keyence", "Keyence"], "TSE"),
        ("東京エレクトロン", "8035.T", ["tokyo electron", "tel", "東エレク"], "TSE"),
        ("ファーストリテイリング", "9983.T", ["fast retailing", "ユニクロ", "uniqlo"], "TSE"),
        ("信越化学", "4063.T", ["shin-etsu chemical", "shin-etsu"], "TSE"),
        ("リクルート", "6098.T", ["recruit", "リクルートホールディングス"], "TSE"),
        ("エムスリー", "2413.T", ["m3", "M3"], "TSE"),
        ("オリエンタルランド", "4661.T", ["oriental land", "ディズニーランド", "TDL"], "TSE"),
        ("日本電産", "6594.T", ["nidec", "ニデック"], "TSE"),
        ("村田製作所", "6981.T", ["murata", "murata manufacturing"], "TSE"),
        # US stocks
        ("アップル", "AAPL", ["apple", "Apple Inc"], "NASDAQ"),
        ("マイクロソフト", "MSFT", ["microsoft", "Microsoft Corp"], "NASDAQ"),
        ("グーグル", "GOOGL", ["google", "alphabet", "Alphabet"], "NASDAQ"),
        ("アマゾン", "AMZN", ["amazon", "Amazon.com"], "NASDAQ"),
        ("エヌビディア", "NVDA", ["nvidia", "NVIDIA"], "NASDAQ"),
        ("メタ", "META", ["meta", "facebook", "Meta Platforms"], "NASDAQ"),
        ("テスラ", "TSLA", ["tesla", "Tesla Inc"], "NASDAQ"),
        ("ネットフリックス", "NFLX", ["netflix", "Netflix Inc"], "NASDAQ"),
    ]

    for company_name, ticker, aliases, market in stocks:
        try:
            await db.execute(
                """INSERT OR IGNORE INTO ticker_dictionary
                   (company_name, ticker, aliases, market) VALUES (?, ?, ?, ?)""",
                (company_name, ticker, json.dumps(aliases, ensure_ascii=False), market)
            )
        except Exception as e:
            logger.debug("Skip seeding %s: %s", company_name, e)


async def lookup_ticker(company_name: str) -> Optional[Dict[str, Any]]:
    """Look up ticker by company name in database."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        # Exact match
        async with db.execute(
            "SELECT * FROM ticker_dictionary WHERE company_name = ? LIMIT 1",
            (company_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)

        # Alias match
        async with db.execute(
            "SELECT * FROM ticker_dictionary"
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                aliases = json.loads(row["aliases"] or "[]")
                if company_name.lower() in [a.lower() for a in aliases]:
                    return dict(row)
    return None


async def get_cached_price(ticker: str, period: str) -> Optional[Dict]:
    """Get cached price data if not expired."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT data FROM price_cache
               WHERE ticker = ? AND period = ? AND expires_at > datetime('now')""",
            (ticker, period)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row["data"])
    return None


async def set_cached_price(ticker: str, period: str, data: Dict) -> None:
    """Cache price data."""
    expires_at = (datetime.now() + timedelta(hours=settings.price_cache_ttl_hours)).isoformat()
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """INSERT OR REPLACE INTO price_cache (ticker, period, data, expires_at)
               VALUES (?, ?, ?, ?)""",
            (ticker, period, json.dumps(data), expires_at)
        )
        await db.commit()


async def save_report(ticker: str, company_name: Optional[str], report_data: Dict) -> int:
    """Save analysis report and return report ID."""
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "INSERT INTO reports (ticker, company_name, report_data) VALUES (?, ?, ?)",
            (ticker, company_name, json.dumps(report_data, ensure_ascii=False))
        )
        await db.commit()
        return cursor.lastrowid


async def get_reports(ticker: str, limit: int = 10) -> List[Dict]:
    """Get recent reports for a ticker."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reports WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
            (ticker, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
