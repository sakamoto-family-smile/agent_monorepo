"""DB の全件コピーと照合 (SQLite ⇄ Postgres のどちら向きにも使う。PROPOSAL-0013 §4.4)。

    # Cloud SQL → ローカル SQLite (コピー先の seed 済み ticker 辞書などを消して入れ直す)
    SRC_DATABASE_URL=postgresql+asyncpg://... \\
    DST_DATABASE_URL=sqlite+aiosqlite:///data/local/stock_analysis.db \\
      uv run python -m ops.db_copy --force

    # 照合だけ (書き込まない)
    uv run python -m ops.db_copy --verify-only

URL は `--src` / `--dst` でも渡せるが、パスワードがシェル履歴や ps に残らないよう env を推奨。

手順:
1. コピー先に alembic upgrade head を当て、コピー元と alembic のリビジョンが一致することを確認
2. コピー先の対象テーブルが空であることを確認 (`--force` なら 1 トランザクション内で消してから入れる)
3. テーブルごとに主キー順でバッチ INSERT (id はそのまま持ち込む)
4. コピー先が Postgres なら連番 (sequence) を max(id) + 1 に合わせる
5. テーブルごとに件数と行の hash を照合し、1 つでも違えば exit 1

`price_cache` (TTL 24h のキャッシュ) は既定で対象外 (`--include-cache` で含める)。
書き込み中の DB をコピーしないこと。旧 active 側を止めてから実行する (切替手順は cutover スクリプト)。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import config
from services.db_models import Base
from sqlalchemy import Connection, Table, delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_TABLES = frozenset({"price_cache"})
DEFAULT_BATCH_SIZE = 500


class CopyError(RuntimeError):
    """コピーを始められない / 続けられない状態 (何も書き込んでいないか、ロールバック済み)。"""


@dataclass(frozen=True)
class TableReport:
    name: str
    src_rows: int
    dst_rows: int
    src_hash: str
    dst_hash: str

    @property
    def ok(self) -> bool:
        return self.src_rows == self.dst_rows and self.src_hash == self.dst_hash


def normalize_url(url: str) -> str:
    """同期ドライバの URL を、アプリと同じ非同期ドライバの URL に直す。"""
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url.removeprefix("sqlite:///")
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url.removeprefix(prefix)
    return url


def redact_url(url: str) -> str:
    """ログ用にパスワードを伏せる。"""
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    creds, _, host = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def target_tables(*, include_cache: bool) -> list[Table]:
    return [
        t
        for t in Base.metadata.sorted_tables
        if include_cache or t.name not in CACHE_TABLES
    ]


def upgrade_schema(url: str) -> None:
    """alembic upgrade head を指定 URL に当てる (alembic/env.py は settings から URL を読む)。"""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    original = config.settings.database_url
    config.settings.database_url = url
    try:
        command.upgrade(cfg, "head")
    finally:
        config.settings.database_url = original


def _order_by(table: Table) -> list:
    return list(table.primary_key.columns)


def _alembic_revision(conn: Connection) -> str | None:
    try:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - テーブルが無い DB は「未管理」として扱う
        conn.rollback()
        return None


def _table_digest(conn: Connection, table: Table) -> tuple[int, str]:
    digest = hashlib.sha256()
    rows = 0
    result = conn.execute(select(table).order_by(*_order_by(table)))
    for row in result.mappings():
        values = [row[c.name] for c in table.columns]
        digest.update(json.dumps(values, ensure_ascii=False, default=str).encode("utf-8"))
        digest.update(b"\n")
        rows += 1
    return rows, digest.hexdigest()


def _count(conn: Connection, table: Table) -> int:
    return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _fix_sequences(conn: Connection, tables: list[Table]) -> None:
    """id を明示して INSERT した後、Postgres の連番を max(id) + 1 に合わせる。"""
    if conn.dialect.name != "postgresql":
        return
    for table in tables:
        for col in table.primary_key.columns:
            if not col.autoincrement or col.type.python_type is not int:
                continue
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence(:t, :c), "
                    f"COALESCE((SELECT MAX({col.name}) FROM {table.name}), 0) + 1, false)"
                ),
                {"t": table.name, "c": col.name},
            )


async def _run_sync(engine: AsyncEngine, fn, *, write: bool):
    if write:
        async with engine.begin() as conn:
            return await conn.run_sync(fn)
    async with engine.connect() as conn:
        return await conn.run_sync(fn)


async def verify(src: AsyncEngine, dst: AsyncEngine, tables: list[Table]) -> list[TableReport]:
    reports = []
    for table in tables:
        src_rows, src_hash = await _run_sync(src, lambda c, t=table: _table_digest(c, t), write=False)
        dst_rows, dst_hash = await _run_sync(dst, lambda c, t=table: _table_digest(c, t), write=False)
        reports.append(TableReport(table.name, src_rows, dst_rows, src_hash, dst_hash))
    return reports


async def copy_all(
    src: AsyncEngine,
    dst: AsyncEngine,
    tables: list[Table],
    *,
    force: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    src_rev = await _run_sync(src, _alembic_revision, write=False)
    dst_rev = await _run_sync(dst, _alembic_revision, write=False)
    if src_rev != dst_rev:
        raise CopyError(
            f"alembic のリビジョンが一致しません (src={src_rev}, dst={dst_rev})。"
            "コピー元を alembic upgrade head してから再実行してください"
        )

    async with src.connect() as src_conn, dst.begin() as dst_conn:
        counts = {t.name: await dst_conn.run_sync(lambda c, t=t: _count(c, t)) for t in tables}
        non_empty = {name: n for name, n in counts.items() if n}
        if non_empty and not force:
            raise CopyError(
                f"コピー先が空ではありません: {non_empty}。上書きするなら --force を付けてください"
            )
        for table in reversed(tables):
            await dst_conn.execute(delete(table))
        copied = {}
        for table in tables:
            copied[table.name] = await _copy_with(src_conn, dst_conn, table, batch_size)
        await dst_conn.run_sync(lambda c: _fix_sequences(c, tables))
    return copied


async def _copy_with(src_conn, dst_conn, table: Table, batch_size: int) -> int:
    # src (読み取り) と dst (書き込み) の 2 接続をまたぐため、行は src から batch 単位で取り出す
    copied = 0
    offset = 0
    while True:
        rows = (
            await src_conn.execute(
                select(table).order_by(*_order_by(table)).limit(batch_size).offset(offset)
            )
        ).mappings().all()
        if not rows:
            return copied
        await dst_conn.execute(insert(table), [dict(r) for r in rows])
        copied += len(rows)
        offset += len(rows)


async def fix_sequences(dst: AsyncEngine, tables: list[Table]) -> None:
    await _run_sync(dst, lambda c: _fix_sequences(c, tables), write=True)


def _print_reports(reports: list[TableReport]) -> None:
    width = max(len(r.name) for r in reports)
    for r in reports:
        mark = "OK " if r.ok else "NG "
        print(f"{mark} {r.name:<{width}}  src={r.src_rows:>7}  dst={r.dst_rows:>7}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="stock-analysis-agent の DB を全件コピーして照合する")
    p.add_argument("--src", default=os.getenv("SRC_DATABASE_URL", ""), help="コピー元 URL (既定: $SRC_DATABASE_URL)")
    p.add_argument("--dst", default=os.getenv("DST_DATABASE_URL", ""), help="コピー先 URL (既定: $DST_DATABASE_URL)")
    p.add_argument("--force", action="store_true", help="コピー先の対象テーブルを消してから入れる")
    p.add_argument("--include-cache", action="store_true", help="price_cache もコピーする")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true", help="照合だけ行う (書き込まない)")
    mode.add_argument("--fix-sequences-only", action="store_true", help="コピー先の連番補正だけ行う")
    args = p.parse_args(argv)
    if not args.src or not args.dst:
        p.error("--src / --dst (または SRC_DATABASE_URL / DST_DATABASE_URL) が必要です")
    if args.batch_size <= 0:
        p.error("--batch-size は 1 以上")
    args.src = normalize_url(args.src)
    args.dst = normalize_url(args.dst)
    if args.src == args.dst:
        p.error("コピー元とコピー先が同じです")
    return args


async def _main_async(args: argparse.Namespace) -> int:
    tables = target_tables(include_cache=args.include_cache)
    src = create_async_engine(args.src)
    dst = create_async_engine(args.dst)
    try:
        if args.fix_sequences_only:
            await fix_sequences(dst, tables)
            print("連番を補正しました")
            return 0
        if not args.verify_only:
            copied = await copy_all(src, dst, tables, force=args.force, batch_size=args.batch_size)
            print(f"コピーしました: {copied}")
        reports = await verify(src, dst, tables)
    finally:
        await src.dispose()
        await dst.dispose()
    _print_reports(reports)
    if all(r.ok for r in reports):
        print("照合 OK")
        return 0
    print("照合 NG: 件数または内容が一致しないテーブルがあります", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)
    print(f"src: {redact_url(args.src)}")
    print(f"dst: {redact_url(args.dst)}")
    try:
        if not (args.verify_only or args.fix_sequences_only):
            upgrade_schema(args.dst)
        return asyncio.run(_main_async(args))
    except CopyError as e:
        print(f"中止: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
