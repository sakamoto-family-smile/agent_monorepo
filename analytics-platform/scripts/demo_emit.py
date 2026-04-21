"""デモ: AnalyticsLogger と OTel を組み合わせて業務ログ JSONL を生成する。

使い方:
  uv run python scripts/demo_emit.py --count 50

標準出力は human-readable、生成される JSONL は `./data/raw/` 以下の
Hive パーティションに書かれる。その後 `make dbt-run` で DuckDB に取り込める。
"""

from __future__ import annotations

import argparse
import asyncio
import random

from opentelemetry import trace

from analytics_platform.config import settings
from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.content import (
    ContentRouter,
    LocalFilePayloadWriter,
)
from analytics_platform.observability.hashing import sha256_prefixed
from analytics_platform.observability.logger import configure_structlog, get_logger
from analytics_platform.observability.sinks.file_sink import RotatingFileSink
from analytics_platform.observability.tracer import setup_tracer


def _build_logger() -> AnalyticsLogger:
    sink = RotatingFileSink(
        root_dir=settings.raw_dir,
        service_name=settings.service_name,
        compress=settings.analytics_compress,
    )
    return AnalyticsLogger(
        service_name=settings.service_name,
        service_version=settings.service_version,
        environment=settings.env,
        sink=sink,
    )


def _build_content_router() -> ContentRouter:
    writer = LocalFilePayloadWriter(root_dir=settings.payloads_dir)
    return ContentRouter(
        writer=writer,
        inline_threshold_bytes=settings.content_inline_threshold_bytes,
    )


MODELS = ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")
TOOLS = ("web_search", "file_read", "shell_exec")


async def _emit_sample_trace(
    tracer: trace.Tracer,
    al: AnalyticsLogger,
    router: ContentRouter,
    session_id: str,
    user_id: str,
    log,
) -> None:
    with tracer.start_as_current_span("agent.turn") as span:
        span.set_attribute("session.id", session_id)

        # 1) 会話開始
        initial_q = "この会話はデモ用のサンプルクエリです。"
        al.emit(
            event_type="conversation_event",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "conversation_phase": "started",
                "agent_id": settings.service_name,
                "initial_query_hash": sha256_prefixed(initial_q),
            },
            user_id=user_id,
            session_id=session_id,
        )

        # 2) ユーザーメッセージ (short → inline)
        msg_id_u = "msg_" + session_id[:8] + "_u"
        content_u = "研究室選びについて相談できますか?"
        stored_u = router.route(
            service_name=settings.service_name,
            event_id=msg_id_u,
            content=content_u,
            mime_type="text/markdown",
        )
        al.emit(
            event_type="message",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "message_id": msg_id_u,
                "message_role": "user",
                "message_index": 0,
                **stored_u.to_fields(),
            },
            user_id=user_id,
            session_id=session_id,
        )

        # 3) LLM 呼び出し
        model = random.choice(MODELS)
        input_tokens = random.randint(500, 3000)
        output_tokens = random.randint(100, 800)
        cache_read = int(input_tokens * random.uniform(0.0, 0.9))
        with tracer.start_as_current_span("llm.call") as llm_span:
            llm_span.set_attribute("llm.model_name", model)
            llm_span.set_attribute("llm.provider", "anthropic")
            llm_span.set_attribute("llm.token_count.prompt", input_tokens)
            llm_span.set_attribute("llm.token_count.completion", output_tokens)
            al.emit(
                event_type="llm_call",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "llm_provider": "anthropic",
                    "llm_model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": 0,
                    "total_cost_usd": round(random.uniform(0.001, 0.1), 5),
                    "latency_ms": random.randint(400, 3500),
                    "ttft_ms": random.randint(200, 1500),
                    "stop_reason": "end_turn",
                },
                user_id=user_id,
                session_id=session_id,
            )

        # 4) ツール呼び出し (ランダム)
        if random.random() < 0.5:
            tool = random.choice(TOOLS)
            al.emit(
                event_type="tool_invocation",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "tool_name": tool,
                    "tool_server": "mcp-demo",
                    "duration_ms": random.randint(50, 1200),
                    "status": "success",
                    "output_size_bytes": random.randint(100, 50000),
                    "retry_count": 0,
                },
                user_id=user_id,
                session_id=session_id,
            )

        # 5) アシスタント応答 (大きめ → URI 退避するケース)
        if random.random() < 0.3:
            content_a = "デモ用長文応答。" * 600  # > 8KB になる想定
        else:
            content_a = "研究室選びで重視すべき点は指導教員との相性です。"
        msg_id_a = "msg_" + session_id[:8] + "_a"
        stored_a = router.route(
            service_name=settings.service_name,
            event_id=msg_id_a,
            content=content_a,
            mime_type="text/markdown",
        )
        al.emit(
            event_type="message",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "message_id": msg_id_a,
                "message_role": "assistant",
                "message_index": 1,
                "parent_message_id": msg_id_u,
                **stored_a.to_fields(),
            },
            user_id=user_id,
            session_id=session_id,
        )

        # 6) たまにエラーを混ぜる
        if random.random() < 0.1:
            al.emit(
                event_type="error_event",
                event_version="1.0.0",
                severity="ERROR",
                fields={
                    "error_type": "RateLimitError",
                    "error_code": "429",
                    "error_message": "Rate limit exceeded",
                    "error_category": "external_api",
                    "is_retriable": True,
                },
                user_id=user_id,
                session_id=session_id,
            )

        # 7) 会話終了
        al.emit(
            event_type="conversation_event",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "conversation_phase": "ended",
                "agent_id": settings.service_name,
                "initial_query_hash": sha256_prefixed(initial_q),
            },
            user_id=user_id,
            session_id=session_id,
        )
        log.info(
            "demo_trace_emitted",
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


async def main_async(count: int) -> None:
    settings.ensure_dirs()
    configure_structlog(level=settings.log_level)
    log = get_logger("demo_emit")

    tracer = setup_tracer(
        service_name=settings.service_name,
        service_version=settings.service_version,
        environment=settings.env,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        otlp_headers=settings.otel_exporter_otlp_headers,
        sampling_ratio=settings.otel_sampling_ratio,
    )
    al = _build_logger()
    router = _build_content_router()

    for i in range(count):
        sid = f"conv_demo_{i:04d}"
        uid = f"u_demo_{random.randint(1, 20):03d}"
        try:
            await _emit_sample_trace(tracer, al, router, sid, uid, log)
        except Exception:  # noqa: BLE001
            log.exception("demo_trace_failed", session_id=sid)

    n = await al.flush()
    log.info("demo_emit_flushed", events_written=n, buffer_remaining=al.buffer_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit demo analytics events.")
    parser.add_argument("--count", type=int, default=20, help="Number of sessions")
    args = parser.parse_args()
    asyncio.run(main_async(args.count))


if __name__ == "__main__":
    main()
