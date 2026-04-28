"""Cloud SQL pgvector の Question Bank に対する smoke verify CLI。

PR A2: スキーマ投入後の動作確認用。本スクリプトは:

1. dummy 768 次元 embedding を持つ verify 用問題 1 件を `add` で投入
2. 同じ embedding で `find_similar` を実行し、score >= 0.999 が返ることを確認
3. `find_by_body_hash` で同レコードが取れることを確認
4. `count` を呼んで件数を表示
5. cleanup として verify 用レコードを削除

使い方:
    # 別ターミナルで Cloud SQL Auth Proxy を起動
    cloud-sql-proxy sakamomo-family-agent:asia-northeast1:driving-license-bot-pg

    # 本ターミナルで verify
    cd driving-license-bot
    make cloudsql-verify

非ゼロ exit code は何らかの異常を意味する。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime

from app.repositories.question_bank.pgvector_impl import (
    PgvectorQuestionBank,
    build_pgvector_pool,
)
from app.repositories.question_bank.protocol import StoredQuestion

logger = logging.getLogger(__name__)

EMBED_DIM = 768
SIMILARITY_THRESHOLD = 0.999  # 同一 embedding の cos 類似度はほぼ 1.0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Smoke-verify Cloud SQL pgvector Question Bank."
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
    )
    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    if not args.project:
        raise SystemExit(
            "ERROR: --project または GOOGLE_CLOUD_PROJECT が必要です（password 取得用）"
        )
    from google.cloud import secretmanager  # type: ignore[import-untyped]

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{args.project}/secrets/{args.password_from_secret}/versions/latest"
    logger.info("[verify_qb] fetching password from %s", name)
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def make_dummy_embedding(seed: float = 0.1) -> list[float]:
    """L2 正規化された 768 次元 embedding（cosine 類似度 1.0 を確実に出すため）。"""
    raw = [seed + i * 1e-4 for i in range(EMBED_DIM)]
    norm = sum(v * v for v in raw) ** 0.5
    return [v / norm for v in raw]


async def _run(args: argparse.Namespace) -> int:
    password = resolve_password(args)
    print(
        f"[verify_qb] connecting host={args.host} port={args.port} "
        f"db={args.database} user={args.user}"
    )

    pool = await build_pgvector_pool(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        database=args.database,
        min_size=1,
        max_size=2,
    )
    bank = PgvectorQuestionBank(pool)
    suffix = uuid.uuid4().hex[:8]
    question_id = f"verify-{suffix}"
    body_hash = f"hash-{suffix}"
    embedding = make_dummy_embedding()

    try:
        # 1. add
        question = StoredQuestion(
            question_id=question_id,
            version=1,
            body_hash=body_hash,
            embedding=embedding,
            applicable_goals=["provisional"],
            category="verify",
            difficulty="easy",
            status="needs_review",
            created_at=datetime.now(UTC),
        )
        t0 = time.perf_counter()
        await bank.add(question)
        t_add = (time.perf_counter() - t0) * 1000
        print(f"[verify_qb] ✓ add ({t_add:.1f} ms)")

        # 2. find_similar with same embedding
        t0 = time.perf_counter()
        hits = await bank.find_similar(embedding, top_k=3)
        t_find = (time.perf_counter() - t0) * 1000
        if not hits:
            print("[verify_qb] FAIL: find_similar returned 0 hits", file=sys.stderr)
            return 2
        top = hits[0]
        print(
            f"[verify_qb] ✓ find_similar top score={top.score:.6f} "
            f"({len(hits)} hits, {t_find:.1f} ms)"
        )
        if top.score < SIMILARITY_THRESHOLD:
            print(
                f"[verify_qb] FAIL: top score {top.score:.6f} < {SIMILARITY_THRESHOLD}",
                file=sys.stderr,
            )
            return 3
        if top.stored.question_id != question_id:
            print(
                f"[verify_qb] FAIL: top question_id={top.stored.question_id} "
                f"!= {question_id}",
                file=sys.stderr,
            )
            return 4

        # 3. find_by_body_hash
        by_hash = await bank.find_by_body_hash(body_hash)
        if by_hash is None or by_hash.question_id != question_id:
            print("[verify_qb] FAIL: find_by_body_hash mismatch", file=sys.stderr)
            return 5
        print("[verify_qb] ✓ find_by_body_hash")

        # 4. count
        n = await bank.count()
        print(f"[verify_qb] ✓ count = {n}")
        n_status = await bank.count(status="needs_review")
        print(f"[verify_qb] ✓ count(status=needs_review) = {n_status}")

        print("[verify_qb] ALL OK.")
        return 0
    finally:
        # 5. cleanup
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM questions WHERE question_id = $1", question_id
            )
        await pool.close()
        print(f"[verify_qb] cleaned up {question_id}")


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
