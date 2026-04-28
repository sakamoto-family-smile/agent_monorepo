"""Cloud SQL Postgres に pgvector extension とスキーマを投入する CLI（手動実行用）。

PR A1 で TF が `driving-license-bot-pg` instance + `question_bank` database +
`app` user を作成済み。本スクリプトは:

1. `app` user の password を Secret Manager (`driving-license-bot-cloudsql-password`)
   から取得（または `--password` で直接指定）
2. Cloud SQL Auth Proxy (`127.0.0.1:5432`) または直接接続で asyncpg pool 経由で
   接続
3. `CREATE EXTENSION vector` + `questions` テーブル + 各種 index を idempotent に
   作成
4. 件数を表示して成功確認

使い方:
    # 別ターミナルで Cloud SQL Auth Proxy を起動
    cloud-sql-proxy sakamomo-family-agent:asia-northeast1:driving-license-bot-pg

    # 本ターミナルで bootstrap
    cd driving-license-bot
    make cloudsql-init                       # 既定: Secret Manager から password 取得
    # または:
    uv run --extra pgvector python scripts/init_question_bank_schema.py
    uv run --extra pgvector python scripts/init_question_bank_schema.py --host 127.0.0.1

teardown 後の再投入も同コマンドで OK（テーブル定義は IF NOT EXISTS）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


SCHEMA_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT PRIMARY KEY,
    version          INTEGER NOT NULL,
    body_hash        TEXT NOT NULL,
    embedding        vector(768) NOT NULL,
    applicable_goals TEXT[] NOT NULL,
    category         TEXT NOT NULL,
    difficulty       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'needs_review',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS questions_embedding_ivfflat
    ON questions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS questions_body_hash_idx ON questions (body_hash);
CREATE INDEX IF NOT EXISTS questions_status_idx ON questions (status);
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap pgvector schema on Cloud SQL Postgres."
    )
    p.add_argument("--host", default=os.getenv("CLOUDSQL_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("CLOUDSQL_PORT", "5432")))
    p.add_argument("--database", default=os.getenv("CLOUDSQL_DB", "question_bank"))
    p.add_argument("--user", default=os.getenv("CLOUDSQL_USER", "app"))
    p.add_argument(
        "--password",
        default=os.getenv("CLOUDSQL_PASSWORD"),
        help="平文 password。未指定なら --password-from-secret から取得。",
    )
    p.add_argument(
        "--password-from-secret",
        default=os.getenv(
            "CLOUDSQL_PASSWORD_SECRET", "driving-license-bot-cloudsql-password"
        ),
        help="Secret Manager の secret 名（既定: driving-license-bot-cloudsql-password）。",
    )
    p.add_argument(
        "--project",
        default=os.getenv("GOOGLE_CLOUD_PROJECT"),
        help="Secret Manager の project id。",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    if not args.project:
        raise SystemExit(
            "ERROR: --project または GOOGLE_CLOUD_PROJECT が必要です（password 取得用）"
        )
    try:
        from google.cloud import secretmanager
    except ImportError as exc:
        raise SystemExit(
            "ERROR: google-cloud-secret-manager がありません。`uv sync` で再インストールしてください。"
        ) from exc
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{args.project}/secrets/{args.password_from_secret}/versions/latest"
    logger.info("[init_schema] fetching password from %s", name)
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


async def _run(args: argparse.Namespace) -> int:
    try:
        import asyncpg
    except ImportError as exc:
        raise SystemExit(
            "ERROR: asyncpg がありません。`uv sync --extra pgvector` で入れてください。"
        ) from exc

    password = resolve_password(args)
    print(
        f"[init_schema] connecting host={args.host} port={args.port} "
        f"db={args.database} user={args.user}"
    )
    try:
        conn = await asyncpg.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            database=args.database,
        )
    except Exception as exc:  # noqa: BLE001 — surface any connection issue
        print(f"[init_schema] FAIL connect: {exc}", file=sys.stderr)
        print(
            "[init_schema] hint: Cloud SQL Auth Proxy が起動しているか確認してください。",
            file=sys.stderr,
        )
        return 2

    try:
        print("[init_schema] applying DDL ...")
        # asyncpg.execute() は単一文しか受け付けないため、ステートメントを分割。
        for stmt in [s.strip() for s in SCHEMA_DDL.split(";") if s.strip()]:
            await conn.execute(stmt)
        print("[init_schema] verifying ...")
        ext_row = await conn.fetchrow(
            "SELECT extname, extversion FROM pg_extension WHERE extname='vector'"
        )
        col_rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='questions' ORDER BY ordinal_position"
        )
        idx_rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename='questions' ORDER BY indexname"
        )
        count = await conn.fetchval("SELECT COUNT(*) FROM questions")

        if ext_row is None:
            print("[init_schema] FAIL: vector extension not installed", file=sys.stderr)
            return 3
        print(f"[init_schema] vector extension: v{ext_row['extversion']}")
        print(f"[init_schema] questions columns ({len(col_rows)}):")
        for r in col_rows:
            print(f"  - {r['column_name']}: {r['data_type']}")
        print(f"[init_schema] indexes ({len(idx_rows)}):")
        for r in idx_rows:
            print(f"  - {r['indexname']}")
        print(f"[init_schema] questions row count: {count}")
        print("[init_schema] OK.")
        return 0
    finally:
        await conn.close()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
