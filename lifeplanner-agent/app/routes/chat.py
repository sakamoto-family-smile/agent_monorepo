"""/api/chat — 自然言語でシナリオに問い合わせる。

スコープ (Phase 3a):
  - `scenario_ids` を明示入力 (1 件: 要約 / 2件以上: 比較)
  - 質問文は任意
  - LLM 応答は Advisor が生成
  - LLM_MOCK_MODE=true や API キー未設定時は MockLLMClient で応答

将来 (Phase 3b): LINE 経由の会話履歴、意図分類の LLM 化
"""

from __future__ import annotations

import logging

from agents.orchestrator import run_chat
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from services.auth import get_household_id
from services.database import get_session_dep
from services.llm_client import LLMClient, get_llm_client
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    scenario_ids: list[int] = Field(..., min_length=1, max_length=5)
    question: str | None = Field(default=None, max_length=1000)


class ChatOut(BaseModel):
    intent: str
    scenario_ids: list[int]
    narrative: str


@router.post("/chat", response_model=ChatOut)
async def chat_endpoint(
    payload: ChatIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
    llm: LLMClient = Depends(get_llm_client),
) -> ChatOut:
    try:
        result = await run_chat(
            session=session,
            household_id=household_id,
            scenario_ids=payload.scenario_ids,
            question=payload.question,
            llm=llm,
        )
    except ValueError as e:
        # "Scenario not found" は 404、それ以外は 400
        msg = str(e)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if msg.startswith("Scenario not found")
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=msg) from e

    logger.info(
        "Chat: household=%s intent=%s scenarios=%s",
        household_id, result.intent.value, result.scenario_ids,
    )
    return ChatOut(
        intent=result.intent.value,
        scenario_ids=result.scenario_ids,
        narrative=result.narrative,
    )
