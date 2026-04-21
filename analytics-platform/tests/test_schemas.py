from __future__ import annotations

from datetime import UTC, datetime

import pytest
from observability.schemas import (
    LlmCallEvent,
    MessageEvent,
    ToolInvocationEvent,
    validate_event,
)
from pydantic import ValidationError


def _base_common(**override: object) -> dict:
    base = {
        "event_id": "e1",
        "event_version": "1.0.0",
        "event_timestamp": datetime.now(UTC).isoformat(),
        "service_name": "svc",
        "service_version": "0.1.0",
        "environment": "local",
        "severity": "INFO",
    }
    base.update(override)
    return base


def test_llm_call_happy_path() -> None:
    event = validate_event(
        _base_common(
            event_type="llm_call",
            llm_provider="anthropic",
            llm_model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=20,
        )
    )
    assert isinstance(event, LlmCallEvent)
    assert event.llm_model == "claude-opus-4-7"
    assert event.cache_read_tokens == 0  # default


def test_typo_event_type_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_event(_base_common(event_type="llm_cal"))


def test_required_field_missing_raises() -> None:
    # llm_call には llm_model / input_tokens が必須
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="llm_call",
                llm_provider="anthropic",
            )
        )


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="llm_call",
                llm_provider="anthropic",
                llm_model="m",
                input_tokens=-1,
                output_tokens=0,
            )
        )


def test_trace_id_must_be_32_hex() -> None:
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="llm_call",
                llm_provider="anthropic",
                llm_model="m",
                input_tokens=1,
                output_tokens=1,
                trace_id="not-hex",
            )
        )


def test_content_hash_prefix_enforced() -> None:
    # prefix 無しは rejected
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="message",
                message_id="m1",
                message_role="user",
                message_index=0,
                content_hash="0" * 64,
            )
        )


def test_message_event_ok() -> None:
    event = validate_event(
        _base_common(
            event_type="message",
            message_id="m1",
            message_role="user",
            message_index=0,
            content_text="hi",
            content_hash="sha256:" + "a" * 64,
            content_size_bytes=2,
        )
    )
    assert isinstance(event, MessageEvent)
    assert event.message_role == "user"


def test_tool_invocation_status_enum() -> None:
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="tool_invocation",
                tool_name="t",
                duration_ms=1,
                status="weird",
            )
        )
    event = validate_event(
        _base_common(
            event_type="tool_invocation",
            tool_name="t",
            duration_ms=1,
            status="success",
        )
    )
    assert isinstance(event, ToolInvocationEvent)


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_event(
            _base_common(
                event_type="llm_call",
                llm_provider="anthropic",
                llm_model="m",
                input_tokens=1,
                output_tokens=1,
                unknown_field="x",
            )
        )
