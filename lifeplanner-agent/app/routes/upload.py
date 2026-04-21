"""POST /api/upload — Money Forward ME CSV を受け取り DB に UPSERT する。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.csv_importer import parse_bytes
from repositories.household import ensure_household
from repositories.transaction import upsert_transactions
from services.auth import get_household_id
from services.database import get_session_dep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB


class UploadResponse(BaseModel):
    household_id: str
    source_file: str
    encoding: str
    total_rows: int
    imported: int
    skipped_transfer: int
    skipped_excluded: int
    skipped_invalid: int
    duplicates_in_file: int
    inserted: int
    updated: int
    unchanged: int


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(
    file: UploadFile = File(..., description="MF ME CSV (Shift-JIS/UTF-8)"),
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> UploadResponse:
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (>{_MAX_UPLOAD_BYTES} bytes)",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    from instrumentation import emit_business, emit_error

    try:
        result = parse_bytes(raw, source_label=file.filename or "<upload>")
    except ValueError as e:
        emit_error(error=e, category="validation", user_id=household_id, severity="WARN")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await ensure_household(session, household_id, name=household_id)
    upsert = await upsert_transactions(session, household_id, result.transactions)
    await session.commit()

    logger.info(
        "Upload: household=%s imported=%d inserted=%d updated=%d",
        household_id, result.imported, upsert.inserted, upsert.updated,
    )

    emit_business(
        domain="csv_import",
        action="csv_imported",
        resource_type="transaction_batch",
        resource_id=result.source_file,
        attributes={
            "encoding": result.encoding,
            "total_rows": result.total_rows,
            "imported": result.imported,
            "inserted": upsert.inserted,
            "updated": upsert.updated,
            "unchanged": upsert.unchanged,
            "skipped_transfer": result.skipped_transfer,
            "skipped_excluded": result.skipped_excluded,
            "skipped_invalid": result.skipped_invalid,
            "duplicates_in_file": result.duplicates_in_file,
            "size_bytes": len(raw),
        },
        user_id=household_id,
    )

    return UploadResponse(
        household_id=household_id,
        source_file=result.source_file,
        encoding=result.encoding,
        total_rows=result.total_rows,
        imported=result.imported,
        skipped_transfer=result.skipped_transfer,
        skipped_excluded=result.skipped_excluded,
        skipped_invalid=result.skipped_invalid,
        duplicates_in_file=result.duplicates_in_file,
        inserted=upsert.inserted,
        updated=upsert.updated,
        unchanged=upsert.unchanged,
    )
