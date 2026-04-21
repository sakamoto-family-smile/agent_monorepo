"""OpenTelemetry TracerProvider の初期化。

`ENV=local` なら Phoenix (http://localhost:6006/v1/traces) に、
`ENV=gcp` なら Langfuse の OTLP endpoint に送る。

サンプリング: local は 100%、gcp は環境変数 `OTEL_SAMPLING_RATIO` で制御。
業務ログ側は常に 100% 書くため、OTel 側をサンプリングしても `trace_id` 突合は機能する。
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_ON,
    ParentBasedTraceIdRatio,
    Sampler,
)

logger = logging.getLogger(__name__)


def _parse_headers(headers_str: str) -> dict[str, str]:
    """`k1=v1,k2=v2` 形式を dict に。空文字は空 dict。"""
    result: dict[str, str] = {}
    for item in headers_str.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, _, value = item.partition("=")
        result[key.strip()] = value.strip()
    return result


def _build_sampler(ratio: float) -> Sampler:
    if ratio >= 1.0:
        return ALWAYS_ON
    ratio = max(0.0, min(1.0, ratio))
    return ParentBasedTraceIdRatio(ratio)


_initialized = False


def setup_tracer(
    *,
    service_name: str,
    service_version: str,
    environment: str,
    otlp_endpoint: str,
    otlp_headers: str = "",
    sampling_ratio: float = 1.0,
) -> trace.Tracer:
    """プロセス全体で一度だけ呼ぶ TracerProvider の初期化。

    二重呼び出しは既存プロバイダを再利用する (Phoenix / Langfuse で重複 span を避ける)。
    """
    global _initialized
    if _initialized:
        return trace.get_tracer(service_name)

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=_build_sampler(sampling_ratio),
    )
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        headers=_parse_headers(otlp_headers) or None,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info(
        "OTel tracer initialized (service=%s, env=%s, endpoint=%s, sampling=%.2f)",
        service_name,
        environment,
        otlp_endpoint,
        sampling_ratio,
    )
    _initialized = True
    return trace.get_tracer(service_name)


def reset_tracer_for_tests() -> None:
    """テスト用: グローバルフラグをリセット。OTel 側の再設定は呼び出し側で実施。"""
    global _initialized
    _initialized = False
