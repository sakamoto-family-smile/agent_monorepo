"""MCP Gateway — FastAPI application.

Intercepts MCP tool calls between the agent and external MCP servers,
applying Inbound + Outbound inspection with passive/active mode support.

Passive mode:  All traffic is logged. Violations are recorded but NOT blocked.
               Use for 1-2 weeks after first deployment to calibrate rules.
Active mode:   Violations are blocked. Alert is sent. External traffic is stopped.
               Switch after verifying false-positive rate is acceptable.

Endpoints:
  GET  /health           Health check
  GET  /mode             Current gateway mode (passive/active)
  POST /mode             Switch gateway mode (body: {"mode": "passive"|"active"})
  GET  /tools            List pinned tool definitions
  GET  /audit-log        Recent audit log entries
  GET  /stats            Rate limiter and cost statistics
  POST /proxy/{tool}     Intercept and forward MCP tool call
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..db.migrations import init_db
from ..db.models import AuditLog
from .destination import DestinationChecker
from .dlp import DLPEngine
from .inbound import InboundInspector
from .injection import InjectionDetector
from .outbound import OutboundInspector
from .rate_limiter import RateLimiter
from .tool_pinning import ToolPinStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scan.yaml"


def _load_gateway_config() -> dict[str, Any]:
    """Load the [gateway] section from scan.yaml."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        with open(_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        return data.get("gateway", {})
    except Exception as exc:
        logger.warning("Failed to load gateway config: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Audit logging helpers
# ---------------------------------------------------------------------------

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
AUDIT_LOG_FILE = LOGS_DIR / "mcp-audit.jsonl"


def _write_audit_jsonl(record: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def _save_audit_log(
    event_type: str,
    tool_name: str | None,
    tool_description_hash: str | None,
    parameters_summary: str,
    result_summary: str,
    client_id: str | None,
    verdict: Literal["PASS", "BLOCK", "LOG_ONLY"],
    block_reason: str | None = None,
    block_detail: str | None = None,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    now = datetime.now(tz=timezone.utc)
    flagged = verdict in ("BLOCK", "LOG_ONLY") and block_reason is not None
    flag_reason = f"{block_reason}: {block_detail}" if block_detail else block_reason

    record = {
        "ts": now.isoformat(),
        "event_type": event_type,
        "verdict": verdict,
        "tool_name": tool_name,
        "tool_description_hash": tool_description_hash,
        "parameters_summary": parameters_summary,
        "result_summary": result_summary,
        "client_id": client_id,
        "flagged": flagged,
        "flag_reason": flag_reason,
    }
    _write_audit_jsonl(record)

    try:
        engine = create_async_engine(settings.database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            entry = AuditLog(
                event_type=event_type,
                tool_name=tool_name,
                tool_description_hash=tool_description_hash,
                parameters_summary=parameters_summary[:500] if parameters_summary else None,
                result_summary=result_summary[:500] if result_summary else None,
                client_id=client_id,
                created_at=now,
                flagged=flagged,
                flag_reason=flag_reason,
            )
            session.add(entry)
            await session.commit()
        await engine.dispose()
    except Exception as exc:
        logger.warning("Failed to save audit log to DB: %s", exc)


# ---------------------------------------------------------------------------
# FastAPI application and singleton components
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MCP Gateway",
    description="MCP Gateway — Inbound/Outbound security inspection with passive/active mode",
    version="0.2.0",
)

# Mode: "passive" logs violations without blocking; "active" blocks and alerts
_gateway_mode: Literal["passive", "active"] = "passive"

_rate_limiter: RateLimiter | None = None
_tool_pin_store: ToolPinStore | None = None
_inbound: InboundInspector | None = None
_outbound: OutboundInspector | None = None

# Target MCP server URL (forward destination when using catch-all proxy)
MCP_TARGET_URL = os.environ.get("MCP_TARGET_URL", "http://localhost:9000")


@app.on_event("startup")
async def startup() -> None:
    global _gateway_mode, _rate_limiter, _tool_pin_store, _inbound, _outbound

    await init_db()

    cfg = _load_gateway_config()
    _gateway_mode = cfg.get("mode", "passive")

    # Build component instances from config
    rl_cfg = cfg.get("rate_limiter", {})
    rate_limiter = RateLimiter(
        max_calls_per_minute=rl_cfg.get("max_calls_per_minute", 100),
        circuit_breaker_threshold=rl_cfg.get("circuit_breaker_threshold", 10),
    )
    _rate_limiter = rate_limiter

    tool_pins = ToolPinStore()
    _tool_pin_store = tool_pins

    injection_detector = InjectionDetector(
        extra_patterns=cfg.get("injection_patterns")
    )
    dlp_engine = DLPEngine()
    dest_checker = DestinationChecker(
        allowed_destinations=cfg.get("allowed_destinations")
    )

    _inbound = InboundInspector(
        rate_limiter=rate_limiter,
        tool_pin_store=tool_pins,
        injection_detector=injection_detector,
        dlp_engine=dlp_engine,
        destination_checker=dest_checker,
        max_usd_per_hour=cfg.get("max_usd_per_hour", 10.0),
    )

    _outbound = OutboundInspector(
        injection_detector=injection_detector,
        dlp_engine=dlp_engine,
        max_response_bytes=cfg.get("max_response_bytes", 10 * 1024 * 1024),
    )

    logger.info(
        "MCP Gateway started on port %s (mode=%s)",
        settings.proxy_port,
        _gateway_mode,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-gateway", "mode": _gateway_mode}


@app.get("/mode")
async def get_mode() -> dict[str, str]:
    """Return current gateway mode."""
    return {"mode": _gateway_mode}


@app.post("/mode")
async def set_mode(request: Request) -> dict[str, str]:
    """Switch gateway mode. Body: {"mode": "passive"|"active"}"""
    global _gateway_mode
    body = await request.json()
    new_mode = body.get("mode", "")
    if new_mode not in ("passive", "active"):
        raise HTTPException(status_code=400, detail="mode must be 'passive' or 'active'")
    old_mode = _gateway_mode
    _gateway_mode = new_mode
    logger.info("Gateway mode changed: %s → %s", old_mode, new_mode)
    return {"mode": _gateway_mode, "previous": old_mode}


@app.get("/tools")
async def list_tools() -> dict[str, Any]:
    if _tool_pin_store is None:
        return {"tools": []}
    pins = await _tool_pin_store.list_pins()
    return {"tools": pins}


@app.get("/audit-log")
async def audit_log(limit: int = 50) -> dict[str, Any]:
    from sqlalchemy import desc, select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
        )
        entries = result.scalars().all()
    await engine.dispose()

    return {
        "entries": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "tool_name": e.tool_name,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "flagged": e.flagged,
                "flag_reason": e.flag_reason,
                "client_id": e.client_id,
            }
            for e in entries
        ]
    }


@app.get("/stats")
async def proxy_stats() -> dict[str, Any]:
    rate_stats = await _rate_limiter.get_stats() if _rate_limiter else {}
    return {
        "mode": _gateway_mode,
        "rate_limiter": rate_stats,
        "target_url": MCP_TARGET_URL,
    }


# ---------------------------------------------------------------------------
# Core: MCP tool call interception
# ---------------------------------------------------------------------------

@app.post("/proxy/{tool_name:path}")
async def proxy_tool_call(tool_name: str, request: Request) -> JSONResponse:
    """Intercept an MCP tool call through the full Inbound → Forward → Outbound pipeline.

    In **passive** mode: violations are logged but requests are still forwarded.
    In **active** mode:  violations immediately return an error; external MCP server
                         never receives the request (or response is dropped).
    """
    if _inbound is None or _outbound is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    client_id = (
        request.headers.get("X-Client-ID")
        or str(request.client.host if request.client else "unknown")
    )

    try:
        body = await request.json()
    except Exception:
        body = {}

    tool_description = body.get("description", "")
    parameters = body.get("parameters", body.get("params", {}))
    destination_url = body.get("destination", MCP_TARGET_URL)
    estimated_cost = float(body.get("estimated_cost_usd", 0.0))

    params_summary = json.dumps(parameters, default=str)[:200]

    # =========================================================
    # INBOUND INSPECTION (checks 1–6)
    # =========================================================
    inbound_verdict = await _inbound.inspect(
        tool_name=tool_name,
        tool_description=tool_description,
        parameters=parameters,
        destination_url=destination_url,
        estimated_cost_usd=estimated_cost,
    )

    if not inbound_verdict.passed:
        reason = inbound_verdict.block_reason
        detail = inbound_verdict.block_detail

        if _gateway_mode == "active":
            # Block: do not forward to external MCP server
            await _save_audit_log(
                event_type=f"inbound_blocked_{(reason or 'unknown').lower()}",
                tool_name=tool_name,
                tool_description_hash=inbound_verdict.description_hash,
                parameters_summary=params_summary,
                result_summary=f"BLOCKED: {detail}",
                client_id=client_id,
                verdict="BLOCK",
                block_reason=reason,
                block_detail=detail,
            )
            raise HTTPException(
                status_code=_block_status_code(reason),
                detail=f"Request blocked by MCP Gateway [{reason}]: {detail}",
            )
        else:
            # Passive: log the violation but continue
            logger.warning(
                "[PASSIVE] Inbound violation (would block in active mode): "
                "[%s] %s — %s",
                tool_name, reason, detail,
            )
            await _save_audit_log(
                event_type=f"inbound_violation_{(reason or 'unknown').lower()}",
                tool_name=tool_name,
                tool_description_hash=inbound_verdict.description_hash,
                parameters_summary=params_summary,
                result_summary=f"PASSIVE LOG: {detail}",
                client_id=client_id,
                verdict="LOG_ONLY",
                block_reason=reason,
                block_detail=detail,
            )

    # =========================================================
    # FORWARD TO EXTERNAL MCP SERVER
    # =========================================================
    forward_url = f"{destination_url.rstrip('/')}/{tool_name}"
    response_data: dict[str, Any] = {}
    status_code = 200

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(forward_url, json=body)
            status_code = resp.status_code
            response_data = resp.json() if resp.content else {}
        if _rate_limiter:
            await _rate_limiter.record_success(tool_name)

    except httpx.ConnectError:
        logger.warning("Downstream MCP server unavailable at %s", forward_url)
        response_data = {
            "status": "gateway_passthrough",
            "tool": tool_name,
            "note": "Downstream MCP server not available. Gateway checks applied.",
        }
        if _rate_limiter:
            await _rate_limiter.record_failure(tool_name)

    except Exception as exc:
        if _rate_limiter:
            await _rate_limiter.record_failure(tool_name)
        raise HTTPException(status_code=502, detail=f"Upstream MCP server error: {exc}")

    # =========================================================
    # OUTBOUND INSPECTION (checks 7–9)
    # =========================================================
    outbound_verdict = _outbound.inspect(response_data, tool_name=tool_name)

    if not outbound_verdict.passed:
        reason = outbound_verdict.block_reason
        detail = outbound_verdict.block_detail

        if _gateway_mode == "active":
            # Drop the response: do not return potentially poisoned data to agent
            await _save_audit_log(
                event_type=f"outbound_blocked_{(reason or 'unknown').lower()}",
                tool_name=tool_name,
                tool_description_hash=inbound_verdict.description_hash,
                parameters_summary=params_summary,
                result_summary=f"RESPONSE DROPPED: {detail}",
                client_id=client_id,
                verdict="BLOCK",
                block_reason=reason,
                block_detail=detail,
            )
            raise HTTPException(
                status_code=502,
                detail=f"MCP server response blocked by Gateway [{reason}]: {detail}",
            )
        else:
            # Passive: log but return response anyway
            logger.warning(
                "[PASSIVE] Outbound violation (would drop in active mode): "
                "[%s] %s — %s",
                tool_name, reason, detail,
            )
            await _save_audit_log(
                event_type=f"outbound_violation_{(reason or 'unknown').lower()}",
                tool_name=tool_name,
                tool_description_hash=inbound_verdict.description_hash,
                parameters_summary=params_summary,
                result_summary=f"PASSIVE LOG: {detail}",
                client_id=client_id,
                verdict="LOG_ONLY",
                block_reason=reason,
                block_detail=detail,
            )

    # =========================================================
    # SUCCESS: log and return to agent
    # =========================================================
    await _save_audit_log(
        event_type="tool_call",
        tool_name=tool_name,
        tool_description_hash=inbound_verdict.description_hash,
        parameters_summary=params_summary,
        result_summary=f"HTTP {status_code}",
        client_id=client_id,
        verdict="PASS",
    )

    return JSONResponse(content=response_data, status_code=status_code)


def _block_status_code(reason: str | None) -> int:
    """Map block reason to an appropriate HTTP status code."""
    codes = {
        "RATE_LIMIT": 429,
        "TOOL_INTEGRITY": 403,
        "INJECTION": 400,
        "DLP_OUTBOUND": 400,
        "DESTINATION": 403,
        "COST_LIMIT": 429,
    }
    return codes.get(reason or "", 400)


def main() -> None:
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.proxy_host, port=settings.proxy_port)


if __name__ == "__main__":
    main()
