import aiosqlite
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from config import settings

logger = logging.getLogger(__name__)

DB_PATH = settings.db_path


async def init_db() -> None:
    """Initialize SQLite database with schema."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
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

            CREATE INDEX IF NOT EXISTS idx_ticker_dict_name ON ticker_dictionary(company_name);
            CREATE INDEX IF NOT EXISTS idx_price_cache_ticker ON price_cache(ticker, period);
            CREATE INDEX IF NOT EXISTS idx_reports_ticker ON reports(ticker);
        """)

        # Seed common Japanese/US stocks
        await _seed_ticker_dictionary(db)
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO price_cache (ticker, period, data, expires_at)
               VALUES (?, ?, ?, ?)""",
            (ticker, period, json.dumps(data), expires_at)
        )
        await db.commit()


async def save_report(ticker: str, company_name: Optional[str], report_data: Dict) -> int:
    """Save analysis report and return report ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO reports (ticker, company_name, report_data) VALUES (?, ?, ?)",
            (ticker, company_name, json.dumps(report_data, ensure_ascii=False))
        )
        await db.commit()
        return cursor.lastrowid


async def get_reports(ticker: str, limit: int = 10) -> List[Dict]:
    """Get recent reports for a ticker."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reports WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
            (ticker, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
