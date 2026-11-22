"""updater の外への通信を PyPI だけに絞るプロキシ (remediation-egress コンテナ)。

    python -m src.remediation egress    # docker compose 用の常駐

updater は内部ネットワーク (外に出られない) にだけつなぎ、``HTTPS_PROXY`` でここを通す。
受け付けるのは ``CONNECT <許可したホスト>:443`` だけで、TLS の中身は見ない (中継するだけ)。
それ以外 (平文の HTTP・別のホスト・別のポート) は 403 で断る。
許可したホストの名前解決はこのコンテナで行うので、updater からは DNS も外に出ない。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re

logger = logging.getLogger(__name__)

DEFAULT_ALLOW = ("pypi.org", "files.pythonhosted.org")
MAX_HEADER_BYTES = 8192
CONNECT_TIMEOUT = 15.0
IDLE_TIMEOUT = 300.0
HTTPS = frozenset({443})
REQUEST = re.compile(r"^CONNECT ([A-Za-z0-9.-]{1,253}):([0-9]{1,5}) HTTP/1\.[01]$")


def parse_allow(value: str) -> frozenset[str]:
    hosts = {h.strip().lower().rstrip(".") for h in value.split(",") if h.strip()}
    return frozenset(hosts or DEFAULT_ALLOW)


def decide(request_line: str, allow: frozenset[str], ports: frozenset[int] = HTTPS) -> tuple[str, int] | str:
    """許可するなら (ホスト, ポート)、断るなら理由。"""
    m = REQUEST.match(request_line.strip())
    if not m:
        return "only CONNECT is allowed"
    host, port = m.group(1).lower().rstrip("."), int(m.group(2))
    if port not in ports:
        return f"port {port} is not allowed"
    if host not in allow:
        return f"host {host} is not allowed"
    return host, port


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT):
            writer.write(data)
            await writer.drain()
    except (TimeoutError, ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
    with contextlib.suppress(Exception):
        await writer.drain()
        writer.close()


def make_handler(allow: frozenset[str], ports: frozenset[int] = HTTPS):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
            await _reply(writer, "400 Bad Request")
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        verdict = decide(line, allow, ports)
        if isinstance(verdict, str):
            logger.warning("deny: %s (%s)", line[:200], verdict)
            await _reply(writer, "403 Forbidden")
            return
        host, port = verdict
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        except (TimeoutError, OSError) as e:
            logger.warning("upstream %s:%d failed: %s", host, port, e)
            await _reply(writer, "502 Bad Gateway")
            return
        logger.info("allow: %s:%d", host, port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    return handle


async def start(host: str, port: int, allow: frozenset[str], ports: frozenset[int] = HTTPS) -> asyncio.Server:
    return await asyncio.start_server(make_handler(allow, ports), host, port, limit=MAX_HEADER_BYTES)


def serve(host: str, port: int, allow: frozenset[str]) -> None:
    async def main() -> None:
        server = await start(host, port, allow)
        logger.info("egress: listening on %s:%d, allow %s", host, port, ", ".join(sorted(allow)))
        async with server:
            await server.serve_forever()

    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        asyncio.run(main())
