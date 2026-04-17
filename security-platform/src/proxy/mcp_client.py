"""Async Streamable HTTP client for downstream MCP servers (supergateway streamable-http mode).

Sends JSON-RPC 2.0 requests via HTTP POST to {base_url}/mcp.
Session is tracked via the Mcp-Session-Id response header.

Usage:
    async with MCPStreamableHTTPSession("http://mcp-brave-search:3002") as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("brave_web_search", {"query": "..."})
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0


class MCPStreamableHTTPSession:
    """One logical MCP session over Streamable HTTP transport (MCP spec 2024-11-05)."""

    def __init__(self, base_url: str, timeout: float = _TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint = f"{self._base_url}/mcp"
        self._timeout = timeout
        self._session_id: str | None = None
        self._counter: int = 0
        self._client: httpx.AsyncClient | None = None

    # -----------------------------------------------------------------------
    # Context manager
    # -----------------------------------------------------------------------

    async def __aenter__(self) -> "MCPStreamableHTTPSession":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        # Terminate the session on the server side
        if self._session_id and self._client:
            try:
                await self._client.delete(
                    self._endpoint,
                    headers={"Mcp-Session-Id": self._session_id},
                )
            except Exception:
                pass
        if self._client:
            await self._client.aclose()

    # -----------------------------------------------------------------------
    # JSON-RPC send/receive
    # -----------------------------------------------------------------------

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    async def _send(self, method: str, params: dict | None = None) -> Any:
        """Send one JSON-RPC request and return the result.

        supergateway streamableHttp always responds with text/event-stream.
        We read line-by-line and stop as soon as we see the first data event.
        """
        assert self._client is not None
        req_id = self._next_id()
        payload: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with self._client.stream(
            "POST", self._endpoint, json=payload, headers=headers
        ) as resp:
            resp.raise_for_status()

            if "mcp-session-id" in resp.headers:
                self._session_id = resp.headers["mcp-session-id"]

            content_type = resp.headers.get("content-type", "")

            if "text/event-stream" in content_type:
                msg = await self._read_sse_response(resp)
            else:
                body = await resp.aread()
                msg = json.loads(body.decode("utf-8", errors="replace"))

        if "error" in msg:
            raise RuntimeError(f"MCP server error: {msg['error']}")
        return msg.get("result")

    @staticmethod
    async def _read_sse_response(resp: Any) -> dict:
        """Read SSE lines until the first data event and parse it as JSON-RPC."""
        buf = b""
        async for chunk in resp.aiter_bytes():
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        return json.loads(data)
        return {}

    async def _notify(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        assert self._client is not None
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            await self._client.post(self._endpoint, json=payload, headers=headers)
        except Exception as exc:
            logger.debug("Notification %s failed (ignored): %s", method, exc)

    # -----------------------------------------------------------------------
    # MCP protocol helpers
    # -----------------------------------------------------------------------

    async def initialize(self) -> dict:
        """Perform the MCP initialize handshake and capture the session ID."""
        result = await self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-security-gateway",
                    "version": "0.2.0",
                },
            },
        )
        await self._notify("notifications/initialized")
        return result or {}

    async def list_tools(self) -> list[dict]:
        """Return the list of tools advertised by the downstream server."""
        result = await self._send("tools/list", {})
        return (result or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a named tool and return the result dict."""
        result = await self._send(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        return result or {}


# Backward-compatible alias
MCPSSESession = MCPStreamableHTTPSession
