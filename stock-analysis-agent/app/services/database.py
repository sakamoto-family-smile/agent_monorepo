"""DB アクセス層 (PROPOSAL-0011 P2-B: SQLAlchemy async)。

旧 raw aiosqlite 実装を SQLAlchemy 2.0 async に置換し、dev=SQLite / prod=Postgres
(shared Cloud SQL) を 1 コードで扱う。公開関数のシグネチャと戻り値の形は従来と
互換を保つ (呼び出し側無改修):
  - init_db()
  - lookup_ticker(company_name) -> dict | None  (ticker/company_name/aliases/market...)
  - get_cached_price(ticker, period) -> list | None  (data 列を json.loads した中身)
  - set_cached_price(ticker, period, data) -> None
  - save_report(ticker, company_name, report_data) -> int  (report_id)
  - get_reports(ticker, limit) -> list[dict]  (report_data は JSON 文字列のまま)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

import config
from services.db_engine import get_engine, get_sessionmaker
from services.db_models import Base, PriceCache, Report, TickerDictionary

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """スキーマ作成 (db_auto_create 時のみ) + ticker 辞書 seed。

    prod Postgres は `db_auto_create=false` + alembic でスキーマ管理するため、
    ここでは seed のみ行う (alembic upgrade はコンテナ起動時に実施)。
    """
    if config.settings.db_auto_create:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await _seed_ticker_dictionary()
    logger.info("Database initialized (url dialect=%s)", _dialect())


def _dialect() -> str:
    return config.settings.resolved_database_url.split(":", 1)[0]


_SEED_STOCKS: list[tuple[str, str, list[str], str]] = [
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
    ("アップル", "AAPL", ["apple", "Apple Inc"], "NASDAQ"),
    ("マイクロソフト", "MSFT", ["microsoft", "Microsoft Corp"], "NASDAQ"),
    ("グーグル", "GOOGL", ["google", "alphabet", "Alphabet"], "NASDAQ"),
    ("アマゾン", "AMZN", ["amazon", "Amazon.com"], "NASDAQ"),
    ("エヌビディア", "NVDA", ["nvidia", "NVIDIA"], "NASDAQ"),
    ("メタ", "META", ["meta", "facebook", "Meta Platforms"], "NASDAQ"),
    ("テスラ", "TSLA", ["tesla", "Tesla Inc"], "NASDAQ"),
    ("ネットフリックス", "NFLX", ["netflix", "Netflix Inc"], "NASDAQ"),
]


async def _seed_ticker_dictionary() -> None:
    """共通銘柄を辞書に seed する (存在チェックで冪等)。"""
    sm = get_sessionmaker()
    async with sm() as session:
        for company_name, ticker, aliases, market in _SEED_STOCKS:
            exists = await session.scalar(
                select(TickerDictionary.id).where(
                    TickerDictionary.company_name == company_name,
                    TickerDictionary.ticker == ticker,
                )
            )
            if exists is None:
                session.add(
                    TickerDictionary(
                        company_name=company_name,
                        ticker=ticker,
                        aliases=json.dumps(aliases, ensure_ascii=False),
                        market=market,
                    )
                )
        await session.commit()


def _ticker_row_to_dict(row: TickerDictionary) -> Dict[str, Any]:
    return {
        "id": row.id,
        "company_name": row.company_name,
        "ticker": row.ticker,
        "aliases": row.aliases,
        "market": row.market,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def lookup_ticker(company_name: str) -> Optional[Dict[str, Any]]:
    """会社名/エイリアスからティッカー辞書を引く (完全一致 → エイリアス一致)。"""
    sm = get_sessionmaker()
    async with sm() as session:
        exact = await session.scalar(
            select(TickerDictionary).where(
                TickerDictionary.company_name == company_name
            ).limit(1)
        )
        if exact is not None:
            return _ticker_row_to_dict(exact)

        rows = (await session.scalars(select(TickerDictionary))).all()
        needle = company_name.lower()
        for row in rows:
            try:
                aliases = json.loads(row.aliases or "[]")
            except json.JSONDecodeError:
                aliases = []
            if needle in [str(a).lower() for a in aliases]:
                return _ticker_row_to_dict(row)
    return None


async def get_cached_price(ticker: str, period: str) -> Optional[List]:
    """有効期限内のキャッシュ価格データ (list) を返す。期限切れ/不在は None。"""
    sm = get_sessionmaker()
    async with sm() as session:
        row = await session.scalar(
            select(PriceCache).where(
                PriceCache.ticker == ticker, PriceCache.period == period
            ).limit(1)
        )
        if row is None:
            return None
        # expires_at は ISO 文字列。現在時刻 (naive ISO) と文字列比較せず datetime で比較。
        if not _is_future(row.expires_at):
            return None
        try:
            return json.loads(row.data)
        except json.JSONDecodeError:
            return None


def _is_future(iso_ts: str) -> bool:
    try:
        return datetime.fromisoformat(iso_ts) > datetime.now()
    except ValueError:
        return False


async def set_cached_price(ticker: str, period: str, data: Dict) -> None:
    """価格データをキャッシュ (UNIQUE(ticker, period) で upsert)。"""
    expires_at = (
        datetime.now() + timedelta(hours=config.settings.price_cache_ttl_hours)
    ).isoformat()
    payload = json.dumps(data)
    sm = get_sessionmaker()
    async with sm() as session:
        row = await session.scalar(
            select(PriceCache).where(
                PriceCache.ticker == ticker, PriceCache.period == period
            ).limit(1)
        )
        if row is None:
            session.add(
                PriceCache(
                    ticker=ticker, period=period, data=payload, expires_at=expires_at
                )
            )
        else:
            row.data = payload
            row.expires_at = expires_at
            row.cached_at = datetime.now().isoformat()
        await session.commit()


async def save_report(
    ticker: str, company_name: Optional[str], report_data: Dict
) -> int:
    """分析レポートを保存し report ID を返す。"""
    sm = get_sessionmaker()
    async with sm() as session:
        report = Report(
            ticker=ticker,
            company_name=company_name,
            report_data=json.dumps(report_data, ensure_ascii=False),
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return int(report.id)


async def get_reports(ticker: str, limit: int = 10) -> List[Dict]:
    """ticker の直近レポートを返す (report_data は JSON 文字列のまま)。"""
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (
            await session.scalars(
                select(Report)
                .where(Report.ticker == ticker)
                .order_by(Report.created_at.desc(), Report.id.desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "company_name": r.company_name,
                "report_data": r.report_data,
                "created_at": r.created_at,
            }
            for r in rows
        ]
