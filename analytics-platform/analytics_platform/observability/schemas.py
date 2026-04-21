"""業務ログ JSONL イベントのスキーマ (Pydantic discriminated union)。

設計書 §6.3 の 7 種類の event_type を、`event_type` フィールドを discriminator として
Union で束ねる。これにより `validate_event()` は:

  1. typo (`"llm_cal"` 等) を弾く
  2. 必須フィールドを event_type ごとに強制 (例: llm_call には llm_model)
  3. IDE の型補完を効かせる

アプリコードは `AnyEvent` を直接使うのではなく、それぞれのクラス
(`LlmCallEvent` 等) を emit 側で使うか、`validate_event(dict)` で辞書から復元する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# ---------------------------------------------------------------------------
# 列挙
# ---------------------------------------------------------------------------

Severity = Literal["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]

MessageRole = Literal["user", "assistant", "system", "tool"]

ConversationPhase = Literal["started", "message_received", "ended", "aborted"]

GuardName = Literal["model_armor", "llm_guard", "custom"]

GuardAction = Literal["allowed", "blocked", "flagged", "redacted"]

ToolStatus = Literal["success", "error", "timeout"]

ErrorCategory = Literal["external_api", "internal", "validation", "timeout", "auth"]


# ---------------------------------------------------------------------------
# 共通ベース
# ---------------------------------------------------------------------------


class _BaseEvent(BaseModel):
    """全イベント共通のフィールド (設計書 §6.2)。"""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=64)
    event_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    event_timestamp: datetime
    service_name: str = Field(..., min_length=1, max_length=128)
    service_version: str = Field(..., min_length=1, max_length=64)
    environment: str = Field(..., min_length=1, max_length=32)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    user_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    severity: Severity


# ---------------------------------------------------------------------------
# 7 種類のイベント
# ---------------------------------------------------------------------------


class LlmCallEvent(_BaseEvent):
    event_type: Literal["llm_call"] = "llm_call"
    llm_provider: str
    llm_model: str
    llm_request_id: str | None = None
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_creation_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0.0)
    latency_ms: int | None = Field(default=None, ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    stop_reason: str | None = None
    request_payload_uri: str | None = None
    response_payload_uri: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class ToolInvocationEvent(_BaseEvent):
    event_type: Literal["tool_invocation"] = "tool_invocation"
    tool_name: str
    tool_server: str | None = None
    tool_version: str | None = None
    input_args_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    input_args_uri: str | None = None
    output_uri: str | None = None
    output_size_bytes: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(..., ge=0)
    status: ToolStatus
    error_type: str | None = None
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)


class MessageEvent(_BaseEvent):
    event_type: Literal["message"] = "message"
    message_id: str
    message_role: MessageRole
    message_index: int = Field(..., ge=0)
    parent_message_id: str | None = None
    content_text: str | None = None
    content_uri: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    content_size_bytes: int | None = Field(default=None, ge=0)
    content_mime_type: str | None = None
    content_truncated: bool = False
    content_preview: str | None = Field(default=None, max_length=1200)
    content_summary: str | None = None
    content_token_count: int | None = Field(default=None, ge=0)
    content_language: str | None = None


class ConversationEvent(_BaseEvent):
    event_type: Literal["conversation_event"] = "conversation_event"
    conversation_phase: ConversationPhase
    agent_id: str | None = None
    initial_query_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class SecurityEvent(_BaseEvent):
    event_type: Literal["security_event"] = "security_event"
    guard_name: GuardName
    check_type: str
    action_taken: GuardAction
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_rules: list[str] = Field(default_factory=list)
    input_snippet_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class BusinessEvent(_BaseEvent):
    event_type: Literal["business_event"] = "business_event"
    business_domain: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ErrorEvent(_BaseEvent):
    event_type: Literal["error_event"] = "error_event"
    error_type: str
    error_code: str | None = None
    error_message: str
    error_category: ErrorCategory
    stack_trace_uri: str | None = None
    is_retriable: bool = False


# ---------------------------------------------------------------------------
# Discriminated Union
# ---------------------------------------------------------------------------

AnyEvent = Annotated[
    LlmCallEvent
    | ToolInvocationEvent
    | MessageEvent
    | ConversationEvent
    | SecurityEvent
    | BusinessEvent
    | ErrorEvent,
    Field(discriminator="event_type"),
]


_ANY_EVENT_ADAPTER: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)


def validate_event(data: dict[str, Any]) -> _BaseEvent:
    """辞書を discriminator でいずれかの具象 Event クラスに検証して返す。

    `extra="forbid"` なので未知フィールドがあれば ValidationError。
    event_type が未知なら discriminator 違反で ValidationError。
    """
    return _ANY_EVENT_ADAPTER.validate_python(data)


# 既知の event_type 一覧 (dbt 側の sources 生成などに使う)
KNOWN_EVENT_TYPES: tuple[str, ...] = (
    "llm_call",
    "tool_invocation",
    "message",
    "conversation_event",
    "security_event",
    "business_event",
    "error_event",
)
