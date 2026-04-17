"""Tests for MCPStreamableHTTPSession (Streamable HTTP MCP client).

Covers:
  - Static helpers: _parse_sse, _read_sse_response
  - Session lifecycle: initialize, list_tools, call_tool
  - Session ID propagation
  - MCP error → RuntimeError
  - Backward-compat alias MCPSSESession
"""
from __future__ import annotations

import json
import pytest
import httpx

from src.proxy.mcp_client import MCPStreamableHTTPSession, MCPSSESession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_body(payload: dict) -> bytes:
    """Encode a JSON-RPC payload as an SSE data event."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n".encode()


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload).encode()


class _MockTransport(httpx.AsyncBaseTransport):
    """Pre-baked mock transport.

    Each call to handle_async_request consumes one entry from ``responses``.
    Entry format: (status_code, headers_dict, body_bytes)
    """

    def __init__(self, responses: list[tuple[int, dict, bytes]]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._index >= len(self._responses):
            raise RuntimeError(
                f"MockTransport: no more responses (index {self._index})"
            )
        status, headers, body = self._responses[self._index]
        self._index += 1
        return httpx.Response(status, headers=headers, content=body)


def _sse_entry(payload: dict, session_id: str = "sess-test-001") -> tuple[int, dict, bytes]:
    headers = {
        "content-type": "text/event-stream",
        "mcp-session-id": session_id,
    }
    return (200, headers, _sse_body(payload))


def _notify_entry() -> tuple[int, dict, bytes]:
    """202 response for notifications/initialized (body ignored)."""
    return (202, {"content-type": "application/json"}, b"{}")


def _make_session(transport: _MockTransport) -> MCPStreamableHTTPSession:
    """Return a session wired to the given mock transport (no context manager)."""
    session = MCPStreamableHTTPSession("http://mcp-test:3002", timeout=5.0)
    session._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return session


# ---------------------------------------------------------------------------
# _parse_sse  (pure static method)
# ---------------------------------------------------------------------------

class TestParseSSE:
    def test_single_data_event(self):
        text = 'event: message\ndata: {"result": {"ok": true}}\n\n'
        assert MCPStreamableHTTPSession._parse_sse(text) == {"result": {"ok": True}}

    def test_last_data_wins(self):
        text = 'data: {"id": 1}\ndata: {"id": 2}\n'
        assert MCPStreamableHTTPSession._parse_sse(text) == {"id": 2}

    def test_empty_text_returns_empty_dict(self):
        assert MCPStreamableHTTPSession._parse_sse("") == {}

    def test_no_data_line_returns_empty_dict(self):
        assert MCPStreamableHTTPSession._parse_sse("event: ping\n\n") == {}

    def test_data_with_leading_space(self):
        text = "data:  {\"x\": 1}\n"
        assert MCPStreamableHTTPSession._parse_sse(text) == {"x": 1}


# ---------------------------------------------------------------------------
# _read_sse_response  (async static method)
# ---------------------------------------------------------------------------

class TestReadSSEResponse:
    @pytest.mark.anyio
    async def test_returns_first_data_payload(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        chunks = [
            b"event: message\n",
            f"data: {json.dumps(payload)}\n".encode(),
            b"\n",
        ]

        class MockResp:
            async def aiter_bytes(self):
                for c in chunks:
                    yield c

        result = await MCPStreamableHTTPSession._read_sse_response(MockResp())
        assert result == payload

    @pytest.mark.anyio
    async def test_empty_stream_returns_empty_dict(self):
        class MockResp:
            async def aiter_bytes(self):
                return
                yield  # make it an async generator

        result = await MCPStreamableHTTPSession._read_sse_response(MockResp())
        assert result == {}


# ---------------------------------------------------------------------------
# MCPStreamableHTTPSession — happy path
# ---------------------------------------------------------------------------

class TestMCPStreamableHTTPSession:
    @pytest.mark.anyio
    async def test_initialize_returns_server_info(self):
        server_info = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "brave-search", "version": "0.1.0"},
        }
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": server_info}),
            _notify_entry(),
        ])
        session = _make_session(transport)

        result = await session.initialize()

        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "brave-search"

    @pytest.mark.anyio
    async def test_initialize_captures_session_id(self):
        transport = _MockTransport([
            _sse_entry(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
                session_id="my-session-xyz",
            ),
            _notify_entry(),
        ])
        session = _make_session(transport)

        await session.initialize()

        assert session._session_id == "my-session-xyz"

    @pytest.mark.anyio
    async def test_session_id_sent_in_subsequent_requests(self):
        tools_result = {"tools": [{"name": "brave_web_search"}]}
        transport = _MockTransport([
            _sse_entry(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
                session_id="sid-propagate",
            ),
            _notify_entry(),
            _sse_entry({"jsonrpc": "2.0", "id": 2, "result": tools_result}),
        ])
        session = _make_session(transport)

        await session.initialize()
        await session.list_tools()

        # The third request (tools/list) should carry the session ID header
        tools_request = transport.requests[2]
        assert tools_request.headers.get("mcp-session-id") == "sid-propagate"

    @pytest.mark.anyio
    async def test_list_tools_returns_tool_names(self):
        tools = [
            {"name": "brave_web_search", "description": "...", "inputSchema": {}},
            {"name": "brave_local_search", "description": "...", "inputSchema": {}},
        ]
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}),
            _notify_entry(),
            _sse_entry({"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}),
        ])
        session = _make_session(transport)

        await session.initialize()
        result = await session.list_tools()

        assert [t["name"] for t in result] == ["brave_web_search", "brave_local_search"]

    @pytest.mark.anyio
    async def test_call_tool_returns_content(self):
        content = [{"type": "text", "text": "Toyota stock price: 3,392"}]
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}),
            _notify_entry(),
            _sse_entry({"jsonrpc": "2.0", "id": 2, "result": {"content": content, "isError": False}}),
        ])
        session = _make_session(transport)

        await session.initialize()
        result = await session.call_tool("brave_web_search", {"query": "Toyota stock", "count": 1})

        assert result["content"] == content
        assert result["isError"] is False

    @pytest.mark.anyio
    async def test_call_tool_sends_correct_json_rpc(self):
        content = [{"type": "text", "text": "result"}]
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}),
            _notify_entry(),
            _sse_entry({"jsonrpc": "2.0", "id": 2, "result": {"content": content}}),
        ])
        session = _make_session(transport)

        await session.initialize()
        await session.call_tool("brave_web_search", {"query": "test"})

        # Inspect the tools/call request body
        req = transport.requests[2]
        body = json.loads(req.content)
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "brave_web_search"
        assert body["params"]["arguments"] == {"query": "test"}

    @pytest.mark.anyio
    async def test_initialize_sends_correct_handshake(self):
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}),
            _notify_entry(),
        ])
        session = _make_session(transport)

        await session.initialize()

        init_req = transport.requests[0]
        body = json.loads(init_req.content)
        assert body["method"] == "initialize"
        assert body["params"]["protocolVersion"] == "2024-11-05"
        assert body["params"]["clientInfo"]["name"] == "mcp-security-gateway"

        notify_req = transport.requests[1]
        notify_body = json.loads(notify_req.content)
        assert notify_body["method"] == "notifications/initialized"
        assert "id" not in notify_body  # notifications have no id


# ---------------------------------------------------------------------------
# MCPStreamableHTTPSession — error handling
# ---------------------------------------------------------------------------

class TestMCPStreamableHTTPSessionErrors:
    @pytest.mark.anyio
    async def test_mcp_server_error_raises_runtime_error(self):
        error = {"code": -32601, "message": "Method not found"}
        transport = _MockTransport([
            _sse_entry({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}),
            _notify_entry(),
            _sse_entry({"jsonrpc": "2.0", "id": 2, "error": error}),
        ])
        session = _make_session(transport)

        await session.initialize()
        with pytest.raises(RuntimeError, match="MCP server error"):
            await session.list_tools()

    @pytest.mark.anyio
    async def test_http_error_propagates(self):
        transport = _MockTransport([
            (500, {"content-type": "application/json"}, b'{"detail": "internal error"}'),
        ])
        session = _make_session(transport)

        with pytest.raises(httpx.HTTPStatusError):
            await session.initialize()

    @pytest.mark.anyio
    async def test_json_response_also_handled(self):
        """If content-type is application/json (not SSE), parse directly."""
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
        transport = _MockTransport([
            (200, {"content-type": "application/json"}, _json_body(payload)),
            _notify_entry(),
        ])
        session = _make_session(transport)

        result = await session.initialize()
        assert result["protocolVersion"] == "2024-11-05"


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------

def test_mcpssesession_is_alias_for_streamable():
    assert MCPSSESession is MCPStreamableHTTPSession


def test_mcpssesession_instantiates_correctly():
    session = MCPSSESession("http://mcp-server:3002")
    assert session._endpoint == "http://mcp-server:3002/mcp"
    assert session._session_id is None
