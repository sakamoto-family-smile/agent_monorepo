"""EDINET 文書 INDEX を `edinet_documents` テーブルに upsert する batch (proposal 0006 Phase 1e)。

実行例:
    # rolling 7 日窓 (default、 cron 毎日 02:00 JST で起動想定)
    python -m app.batch.edinet_index_etl

    # one-shot backfill (初回 / 過去データ投入)
    python -m app.batch.edinet_index_etl --from 2025-06-01 --to 2025-12-31

設計:
- API 1 リクエスト = 1 日分の INDEX。 polite rate (1 req/s) を守って順次叩く
- 既存の `EdinetIndexRepo.upsert_many` で PK=document_id の upsert
  → status 系の遅延変更も反映される (rolling 7 日窓の意義)
- 失敗した日は WARN ログ + 続行 (1 日失敗で全体停止しない)
- 環境変数:
    EDINET_API_KEY            : 必須
    EDINET_DAILY_WINDOW_DAYS  : default 7 (rolling 窓)
    EDINET_MIN_INTERVAL_SEC   : default 1.0 (polite rate)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

from edinet_client import EdinetClient, InMemoryCache

from config import settings
from services.edinet_index_repo import EdinetIndexRepo

logger = logging.getLogger(__name__)


async def run(target_dates: list[date]) -> dict:
    """指定日付の INDEX を取得して DB に upsert。 戻り値は集計結果 dict。"""
    if not settings.edinet_api_key:
        raise RuntimeError("EDINET_API_KEY env is required")

    repo = EdinetIndexRepo()
    summary = {
        "target_days": len(target_dates),
        "succeeded_days": 0,
        "failed_days": 0,
        "upserted_documents": 0,
    }

    # INDEX 取得自体は本体 download を伴わないので、 cache は無くて良い (in-memory ダミー)
    async with EdinetClient(
        api_key=settings.edinet_api_key,
        cache=InMemoryCache(),
        min_interval_sec=settings.edinet_min_interval_sec,
    ) as client:
        for target in target_dates:
            try:
                docs = await client.list_documents(target)
            except Exception:  # noqa: BLE001 — 1 日失敗で全体を止めない
                logger.exception("EDINET INDEX fetch failed for date=%s", target)
                summary["failed_days"] += 1
                continue
            if not docs:
                logger.info("EDINET INDEX empty for date=%s", target)
                summary["succeeded_days"] += 1
                continue
            written = await repo.upsert_many(docs)
            summary["succeeded_days"] += 1
            summary["upserted_documents"] += written
            logger.info(
                "EDINET INDEX upserted date=%s docs=%d", target, written
            )
    return summary


def _resolve_target_dates(
    *,
    rolling_days: int,
    from_date: date | None,
    to_date: date | None,
) -> list[date]:
    """取得対象の日付集合を組み立てる。

    - `--from` / `--to` 両方 None: rolling 過去 N 日 (昨日から遡る)
    - 片方だけ指定: もう片方を today にして補完
    - 両方指定: 範囲内の全日付
    """
    today = date.today()
    if from_date is None and to_date is None:
        return [today - timedelta(days=i + 1) for i in range(rolling_days)]
    if from_date is None:
        from_date = today
    if to_date is None:
        to_date = today
    if from_date > to_date:
        raise ValueError(f"--from ({from_date}) must be <= --to ({to_date})")
    return [
        from_date + timedelta(days=i)
        for i in range((to_date - from_date).days + 1)
    ]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edinet-index-etl",
        description="EDINET INDEX を edinet_documents に upsert する batch",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=date.fromisoformat,
        default=None,
        help="backfill 開始日 (YYYY-MM-DD)。 default は rolling 窓",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=date.fromisoformat,
        default=None,
        help="backfill 終了日 (YYYY-MM-DD)。 default は --from と同日 or today",
    )
    parser.add_argument(
        "--rolling-days",
        type=int,
        default=int(getattr(settings, "edinet_daily_window_days", 7)),
        help="rolling 窓の日数 (--from/--to 未指定時のみ)。 default 7 (env EDINET_DAILY_WINDOW_DAYS)",
    )
    return parser.parse_args(argv)


async def main_async(argv: list[str]) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    target_dates = _resolve_target_dates(
        rolling_days=args.rolling_days,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    logger.info(
        "edinet_index_etl: target_days=%d (%s〜%s)",
        len(target_dates),
        target_dates[0] if target_dates else "—",
        target_dates[-1] if target_dates else "—",
    )

    # EDINET (edinet_documents) は P2-B では aiosqlite 据え置き。core init_db は
    # 本テーブルを作らないため、repo 自身でスキーマを用意する (P3 で Cloud SQL 移行)。
    await EdinetIndexRepo().ensure_schema()
    summary = await run(target_dates)
    logger.info("edinet_index_etl finished: %s", summary)
    return 0 if summary["failed_days"] == 0 else 1


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "main_async", "run"]
