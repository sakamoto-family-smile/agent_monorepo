from __future__ import annotations

import pytest

from analytics_platform.observability import tracer as tracer_mod


@pytest.fixture(autouse=True)
def _reset_tracer() -> None:
    tracer_mod.reset_tracer_for_tests()
    yield
    tracer_mod.reset_tracer_for_tests()


def test_parse_headers_basic() -> None:
    assert tracer_mod._parse_headers("a=1,b=2") == {"a": "1", "b": "2"}
    assert tracer_mod._parse_headers("") == {}
    assert tracer_mod._parse_headers(" a=b ") == {"a": "b"}
    # 壊れた segment は無視
    assert tracer_mod._parse_headers("a=1,nope,b=2") == {"a": "1", "b": "2"}


def test_build_sampler_full() -> None:
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    assert tracer_mod._build_sampler(1.0) is ALWAYS_ON


def test_build_sampler_ratio() -> None:
    # ParentBasedTraceIdRatio を返す
    sampler = tracer_mod._build_sampler(0.5)
    assert sampler is not None
    # out of range は clamp される
    tracer_mod._build_sampler(-1.0)
    tracer_mod._build_sampler(2.0)


def test_setup_tracer_is_idempotent(tmp_path) -> None:
    # 二回呼んでも例外にならない (グローバル provider を再利用)
    t1 = tracer_mod.setup_tracer(
        service_name="svc",
        service_version="v",
        environment="local",
        otlp_endpoint="http://127.0.0.1:1/v1/traces",
        sampling_ratio=1.0,
    )
    t2 = tracer_mod.setup_tracer(
        service_name="svc",
        service_version="v",
        environment="local",
        otlp_endpoint="http://127.0.0.1:1/v1/traces",
        sampling_ratio=1.0,
    )
    assert t1 is not None
    assert t2 is not None
