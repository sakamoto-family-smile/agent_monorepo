"""/internal/run-pipeline — cron 等から叩かれる手動トリガ。"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from publisher.line_client import get_line_client
from repositories.dedup_repo import DedupRepo
from services.llm_factory import build_llm_client
from services.pipeline import run_pipeline
from services.source_config import load_sources

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


_dedup_repo: DedupRepo | None = None


def get_dedup_repo() -> DedupRepo:
    global _dedup_repo
    if _dedup_repo is None:
        _dedup_repo = DedupRepo(db_path=settings.tech_news_db_path)
    return _dedup_repo


def set_dedup_repo(repo: DedupRepo | None) -> None:
    global _dedup_repo
    _dedup_repo = repo


@router.post("/run-pipeline")
async def run_pipeline_endpoint() -> dict:
    """ニュース収集 → LINE 配信を 1 回実行する。

    認証なし。Phase 4 で GCP 移行時に Cloud Run → Cloud Scheduler OIDC 認証に切替。
    """
    try:
        sources = load_sources(settings.pipeline_sources_path)
    except Exception as exc:
        logger.exception("failed to load sources.yaml")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"sources config load error: {exc}",
        ) from exc

    dedup = get_dedup_repo()
    await dedup.initialize()

    llm = build_llm_client()
    line_client = get_line_client(
        settings.line_channel_secret, settings.line_channel_access_token
    )

    try:
        result = await run_pipeline(
            llm=llm, line=line_client, dedup=dedup, sources=sources
        )
    finally:
        if line_client is not None:
            await line_client.close()

    return asdict(result)
