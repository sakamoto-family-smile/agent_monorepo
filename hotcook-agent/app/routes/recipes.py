"""POST /api/recipes/suggest — 食材入力から ホットクックメニューを提案する。"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException

from agents.recipe_suggester import normalize_inputs_for_history, suggest_recipes
from analytics_platform.observability.hashing import sha256_prefixed
from config import settings
from instrumentation import get_analytics_logger
from models.recipe import SuggestRequest, SuggestResponse
from services.database import save_suggestion_history

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/recipes/suggest", response_model=SuggestResponse)
async def suggest(request: SuggestRequest) -> SuggestResponse:
    al = get_analytics_logger()
    session_id = f"recipe_{uuid.uuid4().hex[:16]}"
    request_hash = sha256_prefixed(request.model_dump_json())

    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "started",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": request_hash,
        },
        session_id=session_id,
    )

    try:
        result = suggest_recipes(request)
    except FileNotFoundError as exc:
        # menu-catalog.json 不在
        logger.exception("menu catalog not found")
        al.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity="ERROR",
            fields={
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
                "error_category": "config",
                "is_retriable": False,
            },
            session_id=session_id,
        )
        await al.flush()
        raise HTTPException(
            status_code=503,
            detail="menu-catalog.json が見つかりません。`make seed` を実行してください。",
        ) from exc
    except Exception as exc:
        logger.exception("recipe suggestion failed")
        al.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity="ERROR",
            fields={
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
                "error_category": "internal",
                "is_retriable": False,
            },
            session_id=session_id,
        )
        al.emit(
            event_type="conversation_event",
            event_version="1.0.0",
            severity="WARN",
            fields={
                "conversation_phase": "aborted",
                "agent_id": settings.analytics_service_name,
                "initial_query_hash": request_hash,
            },
            session_id=session_id,
        )
        await al.flush()
        raise

    # 履歴保存 (失敗しても提案結果は返す)
    try:
        await save_suggestion_history(
            requested_ingredients=normalize_inputs_for_history(request.ingredients),
            suggested_menu_nos=json.dumps(
                [c.menu_no for c in result.candidates], ensure_ascii=False
            ),
            mode=request.mode,
        )
    except Exception:
        logger.exception("save_suggestion_history failed (non-fatal)")

    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "business_domain": "hotcook",
            "action": "recipe_suggested",
            "resource_type": "suggestion",
            "resource_id": session_id,
            "attributes": {
                "ingredient_count": len(request.ingredients),
                "top_n": request.top_n,
                "mode": request.mode,
                "max_cook_minutes": request.max_cook_minutes,
                "require_reservation": request.require_reservation,
                "require_no_mixer": request.require_no_mixer,
                "candidates_returned": len(result.candidates),
                "top_menu_nos": [c.menu_no for c in result.candidates],
                "fallback_used": result.fallback_hint is not None,
            },
        },
        session_id=session_id,
    )
    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "ended",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": request_hash,
        },
        session_id=session_id,
    )
    await al.flush()

    return result
