"""EDINET API v2 HTTP client (async)。

公式 API spec: <https://disclosure2.edinet-fsa.go.jp/weee0030.aspx>

主要エンドポイント:
- GET /api/v2/documents.json?date=YYYY-MM-DD&type=2&Subscription-Key=...
    その日に提出された全書類のメタデータ
- GET /api/v2/documents/<docID>?type=<1-5>&Subscription-Key=...
    指定 docID の本体。 type: 1=提出本文書 + 添付, 2=PDF, 3=代替書面 / 添付, 4=英文ファイル, 5=CSV

rate limit / retry:
- per-instance の `min_interval_sec` (default 1.0) で連続リクエスト間隔を保つ
- 5xx は tenacity で指数バックオフ (max 3 回)、 4xx は即 raise
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .cache import Cache, ContentType
from .code_resolver import EdinetCodeResolver
from .types import DocumentBody, DocumentMetadata, DocumentType

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"


class _RetryableError(Exception):
    """tenacity リトライ判定のための内部マーカー。"""


class EdinetClient:
    """EDINET API v2 ラッパ。 `async with` で使う。

    Example:
        async with EdinetClient(api_key="...", cache=LocalCache(...)) as client:
            docs = await client.list_documents(date(2026, 5, 22))
            body = await client.download("S100ABC1", content_type="pdf")
    """

    def __init__(
        self,
        *,
        api_key: str,
        cache: Cache,
        code_resolver: EdinetCodeResolver | None = None,
        user_agent: str = "edinet-client/0.1 (+https://github.com/sakamoto-family-smile/agent_monorepo)",
        min_interval_sec: float = 1.0,
        max_retries: int = 3,
        timeout_sec: float = 60.0,
        base_url: str = _BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required (register at disclosure2.edinet-fsa.go.jp)")
        self._api_key = api_key
        self._cache = cache
        self._code_resolver = code_resolver
        self._user_agent = user_agent
        self._min_interval_sec = min_interval_sec
        self._max_retries = max_retries
        self._timeout_sec = timeout_sec
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def __aenter__(self) -> EdinetClient:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_sec,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ─────────────────────────────────────────────────────────
    # public API
    # ─────────────────────────────────────────────────────────

    async def list_documents(self, target: date) -> list[DocumentMetadata]:
        """指定日の文書 INDEX を取得 (`/api/v2/documents.json`、 type=2 で full metadata)。

        EDINET INDEX には submitDateTime=null の匿名 / 取下げエントリ (全フィールド
        null) が日常的に混入する (1 日数十件程度)。 これらは parse できないので
        debug log のみ吐いて skip し、 残りの正常な書類は確実に返す。
        """
        params = {
            "date": target.isoformat(),
            "type": "2",
            "Subscription-Key": self._api_key,
        }
        payload = await self._get_json(f"{self._base_url}/documents.json", params=params)
        results = payload.get("results", []) or []

        parsed: list[DocumentMetadata] = []
        skipped = 0
        for item in results:
            meta = _to_document_metadata(item)
            if meta is None:
                skipped += 1
                continue
            parsed.append(meta)
        if skipped:
            logger.debug(
                "skipped %d incomplete EDINET INDEX entries for date=%s (e.g., null submitDateTime)",
                skipped,
                target,
            )
        return parsed

    def resolve_edinet_code(self, ticker: str) -> str | None:
        """ticker (e.g., "7203" / "7203.T") から EDINET code を返す。

        `code_resolver` が constructor で渡されていない場合は RuntimeError。
        """
        if self._code_resolver is None:
            raise RuntimeError(
                "EdinetClient was constructed without code_resolver; "
                "pass code_resolver=EdinetCodeResolver.from_csv_path(...) to enable ticker lookup"
            )
        return self._code_resolver.resolve_edinet_code(ticker)

    async def download(
        self,
        document_id: str,
        *,
        content_type: ContentType = "pdf",
    ) -> DocumentBody:
        """書類本体を取得 (cache 経由)。

        cache 命中時は HTTP を打たない。 miss 時は EDINET から取得 → cache 投入。
        """
        cached = await self._cache.get(document_id, content_type)
        if cached is not None:
            return DocumentBody(
                document_id=document_id,
                content_type=content_type,
                bytes_payload=cached,
                fetched_at=datetime.now(UTC),
                from_cache=True,
            )

        type_code = _content_type_to_api_type(content_type)
        params = {"type": type_code, "Subscription-Key": self._api_key}
        url = f"{self._base_url}/documents/{document_id}"
        payload = await self._get_bytes(url, params=params)
        await self._cache.put(document_id, content_type, payload)
        return DocumentBody(
            document_id=document_id,
            content_type=content_type,
            bytes_payload=payload,
            fetched_at=datetime.now(UTC),
            from_cache=False,
        )

    # ─────────────────────────────────────────────────────────
    # private
    # ─────────────────────────────────────────────────────────

    async def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        resp = await self._request("GET", url, params=params)
        return resp.json()

    async def _get_bytes(self, url: str, *, params: dict[str, str]) -> bytes:
        resp = await self._request("GET", url, params=params)
        return resp.content

    async def _request(
        self, method: str, url: str, *, params: dict[str, str]
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("EdinetClient must be used as async context manager")

        async with self._lock:
            await self._wait_interval()
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self._max_retries + 1),
                    wait=wait_exponential(multiplier=1.0),
                    retry=retry_if_exception_type(_RetryableError),
                    reraise=False,
                ):
                    with attempt:
                        return await self._do_request(method, url, params)
            except RetryError as err:
                cause = err.last_attempt.exception()
                if isinstance(cause, _RetryableError) and cause.__cause__ is not None:
                    raise cause.__cause__
                raise
            finally:
                self._last_request_at = time.monotonic()
            raise RuntimeError("unreachable")  # pragma: no cover

    async def _do_request(
        self, method: str, url: str, params: dict[str, str]
    ) -> httpx.Response:
        assert self._client is not None
        # API key はログに残さない (params の "Subscription-Key" は logger.debug でも避ける)
        safe_params = {k: ("***" if k == "Subscription-Key" else v) for k, v in params.items()}
        logger.debug("EDINET %s %s params=%s", method, url, safe_params)
        response = await self._client.request(method, url, params=params)
        if 500 <= response.status_code < 600:
            err = httpx.HTTPStatusError(
                f"EDINET server error {response.status_code}",
                request=response.request,
                response=response,
            )
            raise _RetryableError(str(err)) from err
        if response.status_code == 429:
            err = httpx.HTTPStatusError(
                "EDINET rate limit (429)", request=response.request, response=response
            )
            raise _RetryableError(str(err)) from err
        response.raise_for_status()
        return response

    async def _wait_interval(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_interval_sec - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


# ─────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────


def _content_type_to_api_type(content_type: ContentType) -> str:
    """ContentType → EDINET API の `type` パラメータ。"""
    if content_type == "pdf":
        return "2"
    if content_type == "xbrl_zip":
        return "1"
    if content_type == "attach_zip":
        return "3"
    raise ValueError(f"unknown content_type: {content_type}")


def _to_document_metadata(item: dict[str, Any]) -> DocumentMetadata | None:
    """EDINET API レスポンス 1 件を `DocumentMetadata` に正規化。

    EDINET INDEX には submitDateTime / docID / edinetCode が全 null の匿名
    エントリが日常的に混入する (1 日 ~数十件)。 これらは正規化不能なので
    `None` を返し、 caller (`list_documents`) で skip させる。
    """
    submit_dt = item.get("submitDateTime") or item.get("submitDate") or ""
    submit_date = _parse_yyyymmdd(submit_dt[:10])
    if submit_date is None:
        return None
    if not item.get("docID") or not item.get("edinetCode"):
        return None

    period_end_str = item.get("periodEnd") or item.get("periodStart") or None
    period_end = _parse_yyyymmdd(period_end_str) if period_end_str else None

    doc_type_code = (item.get("docTypeCode") or "").strip()
    try:
        doc_type: DocumentType | str = DocumentType(doc_type_code)
    except ValueError:
        doc_type = doc_type_code  # 未知コードはそのまま str で保持

    return DocumentMetadata(
        document_id=item["docID"],
        edinet_code=item["edinetCode"],
        securities_code=(item.get("secCode") or None),
        submitter_name=item.get("filerName") or "",
        document_type=doc_type,
        submit_date=submit_date,
        period_end=period_end,
        description=item.get("docDescription") or "",
        withdrawal_status=_to_int(item.get("withdrawalStatus"), default=0),
        disclosure_status=_to_int(item.get("disclosureStatus"), default=0),
        doc_info_edit_status=_to_int(item.get("docInfoEditStatus"), default=0),
        xbrl_flag=_to_flag(item.get("xbrlFlag")),
        pdf_flag=_to_flag(item.get("pdfFlag")),
        attach_doc_flag=_to_flag(item.get("attachDocFlag")),
    )


def _parse_yyyymmdd(value: str | None) -> date | None:
    """YYYY-MM-DD を `date` に変換。 None / 空文字 / 不正な文字列は None を返す。"""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_flag(value: Any) -> bool:
    """EDINET の `*Flag` は文字列 "1" / "0" で返ってくる。"""
    if value is None:
        return False
    return str(value).strip() == "1"


__all__ = ["EdinetClient"]
