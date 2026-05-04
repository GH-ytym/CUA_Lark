"""Capability registry for schema, payload normalization, and CLI mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import CapabilityId, IntentType


@dataclass(frozen=True)
class CapabilitySpec:
    """Executable capability contract used by parser and executors."""

    capability_id: CapabilityId
    intent_type: IntentType
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = tuple()
    required_field_groups: tuple[tuple[str, tuple[str, ...]], ...] = tuple()
    default_identity: str = ""
    cli_tool_family: str = ""
    cli_operation: str = ""
    aliases: dict[str, str] = field(default_factory=dict)

    @property
    def payload_fields(self) -> tuple[str, ...]:
        return self.required_fields + self.optional_fields


CAPABILITY_REGISTRY: dict[CapabilityId, CapabilitySpec] = {
    CapabilityId.IM_MESSAGE_SEND: CapabilitySpec(
        capability_id=CapabilityId.IM_MESSAGE_SEND,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("text",),
        optional_fields=("chat_hint", "chat_id", "user_id", "idempotency_key", "identity"),
        required_field_groups=(("chat_hint", ("chat_hint", "chat_id", "user_id")),),
        default_identity="user",
        cli_tool_family="lark-im",
        cli_operation="message_send",
        aliases={"message_text": "text", "message": "text", "target": "chat_hint", "recipient": "chat_hint"},
    ),
    CapabilityId.IM_MESSAGES_REPLY: CapabilitySpec(
        capability_id=CapabilityId.IM_MESSAGES_REPLY,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("text",),
        optional_fields=("message_id", "thread_id", "message_hint", "reply_in_thread", "idempotency_key", "identity"),
        required_field_groups=(("message_hint", ("message_id", "thread_id", "message_hint")),),
        default_identity="user",
        cli_tool_family="lark-im",
        cli_operation="messages_reply",
        aliases={"message_text": "text", "content": "text", "target_message": "message_hint"},
    ),
    CapabilityId.IM_MESSAGES_SEARCH: CapabilitySpec(
        capability_id=CapabilityId.IM_MESSAGES_SEARCH,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("query",),
        optional_fields=("chat_hint", "chat_id", "sender_hint", "start_time", "end_time", "limit", "identity"),
        default_identity="user",
        cli_tool_family="lark-im",
        cli_operation="messages_search",
        aliases={"keyword": "query", "text": "query", "q": "query"},
    ),
    CapabilityId.IM_CHAT_MESSAGES_LIST: CapabilitySpec(
        capability_id=CapabilityId.IM_CHAT_MESSAGES_LIST,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=tuple(),
        optional_fields=("chat_hint", "chat_id", "user_id", "start_time", "end_time", "limit", "identity"),
        required_field_groups=(("chat_hint", ("chat_hint", "chat_id", "user_id")),),
        default_identity="user",
        cli_tool_family="lark-im",
        cli_operation="chat_messages_list",
        aliases={"count": "limit"},
    ),
    CapabilityId.IM_CHAT_SEARCH: CapabilitySpec(
        capability_id=CapabilityId.IM_CHAT_SEARCH,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("query",),
        optional_fields=("member_hints", "limit", "identity"),
        default_identity="user",
        cli_tool_family="lark-im",
        cli_operation="chat_search",
        aliases={"keyword": "query", "name": "query"},
    ),
    CapabilityId.IM_CHAT_CREATE: CapabilitySpec(
        capability_id=CapabilityId.IM_CHAT_CREATE,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("name",),
        optional_fields=("member_hints", "description", "identity"),
        default_identity="bot",
        cli_tool_family="lark-im",
        cli_operation="chat_create",
        aliases={"title": "name", "chat_name": "name"},
    ),
    CapabilityId.CALENDAR_CREATE: CapabilitySpec(
        capability_id=CapabilityId.CALENDAR_CREATE,
        intent_type=IntentType.CALENDAR_RESCHEDULE,
        required_fields=("title", "start_time", "end_time"),
        optional_fields=("attendees", "location", "description"),
        cli_tool_family="lark-calendar",
        cli_operation="event_create",
    ),
    CapabilityId.CALENDAR_RESCHEDULE: CapabilitySpec(
        capability_id=CapabilityId.CALENDAR_RESCHEDULE,
        intent_type=IntentType.CALENDAR_RESCHEDULE,
        required_fields=("event_hint", "target_time"),
        optional_fields=("source_time", "calendar_id"),
        cli_tool_family="lark-calendar",
        cli_operation="event_reschedule",
    ),
    CapabilityId.CALENDAR_AGENDA: CapabilitySpec(
        capability_id=CapabilityId.CALENDAR_AGENDA,
        intent_type=IntentType.CALENDAR_RESCHEDULE,
        required_fields=("time_range",),
        optional_fields=("user_hints",),
        cli_tool_family="lark-calendar",
        cli_operation="agenda",
        aliases={"range": "time_range", "when": "time_range", "users": "user_hints"},
    ),
    CapabilityId.CALENDAR_FREEBUSY: CapabilitySpec(
        capability_id=CapabilityId.CALENDAR_FREEBUSY,
        intent_type=IntentType.CALENDAR_RESCHEDULE,
        required_fields=("time_range",),
        optional_fields=("user_hints",),
        cli_tool_family="lark-calendar",
        cli_operation="freebusy",
        aliases={"range": "time_range", "when": "time_range", "users": "user_hints"},
    ),
    CapabilityId.DOC_CREATE: CapabilitySpec(
        capability_id=CapabilityId.DOC_CREATE,
        intent_type=IntentType.DOC_CREATE,
        required_fields=("title",),
        optional_fields=("content", "folder_token"),
        cli_tool_family="lark-doc",
        cli_operation="doc_create",
        aliases={"name": "title", "body": "content"},
    ),
    CapabilityId.DOC_UPDATE: CapabilitySpec(
        capability_id=CapabilityId.DOC_UPDATE,
        intent_type=IntentType.DOC_CREATE,
        required_fields=("content", "doc_token"),
        optional_fields=("title",),
        cli_tool_family="lark-doc",
        cli_operation="doc_update",
        aliases={"name": "title", "body": "content", "doc": "doc_token"},
    ),
    CapabilityId.DOC_SEARCH: CapabilitySpec(
        capability_id=CapabilityId.DOC_SEARCH,
        intent_type=IntentType.DOC_CREATE,
        required_fields=("query",),
        cli_tool_family="lark-doc",
        cli_operation="doc_search",
        aliases={"keyword": "query", "text": "query", "q": "query"},
    ),
    CapabilityId.SHEET_UPDATE: CapabilitySpec(
        capability_id=CapabilityId.SHEET_UPDATE,
        intent_type=IntentType.SHEET_UPDATE,
        required_fields=("cell", "value"),
        optional_fields=("spreadsheet_token", "sheet_id", "sheet_hint"),
        cli_tool_family="lark-sheets",
        cli_operation="sheet_write",
    ),
    CapabilityId.SHEET_READ: CapabilitySpec(
        capability_id=CapabilityId.SHEET_READ,
        intent_type=IntentType.SHEET_UPDATE,
        required_fields=("cell",),
        optional_fields=("spreadsheet_token", "sheet_id", "sheet_hint"),
        cli_tool_family="lark-sheets",
        cli_operation="sheet_read",
    ),
    CapabilityId.CONTACT_SEARCH: CapabilitySpec(
        capability_id=CapabilityId.CONTACT_SEARCH,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("query",),
        optional_fields=("limit",),
        cli_tool_family="lark-contact",
        cli_operation="contact_search",
        aliases={"keyword": "query", "name": "query", "text": "query", "q": "query"},
    ),
    CapabilityId.TASK_CREATE: CapabilitySpec(
        capability_id=CapabilityId.TASK_CREATE,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("title",),
        optional_fields=("assignee_hints", "due_time", "description"),
        cli_tool_family="lark-task",
        cli_operation="task_create",
        aliases={"name": "title", "content": "description"},
    ),
    CapabilityId.MAIL_SEND: CapabilitySpec(
        capability_id=CapabilityId.MAIL_SEND,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("subject", "body"),
        optional_fields=("to_hints", "to", "cc", "attachments"),
        cli_tool_family="lark-mail",
        cli_operation="mail_send",
        aliases={"title": "subject", "content": "body", "text": "body", "user_id": "to_hints"},
    ),
    CapabilityId.BASE_RECORD_CREATE: CapabilitySpec(
        capability_id=CapabilityId.BASE_RECORD_CREATE,
        intent_type=IntentType.MESSAGE_SEND,
        required_fields=("record",),
        optional_fields=("base_hint", "table_hint"),
        cli_tool_family="lark-base",
        cli_operation="record_create",
        aliases={"base": "base_hint", "table": "table_hint", "fields": "record"},
    ),
}


def get_capability_spec(capability_id: CapabilityId) -> CapabilitySpec | None:
    """Return the schema for a supported capability."""
    return CAPABILITY_REGISTRY.get(capability_id)


def normalize_payload(capability_id: CapabilityId, payload: dict[str, Any]) -> dict[str, object]:
    """Normalize model output into the capability schema."""
    spec = get_capability_spec(capability_id)
    if spec is None:
        return dict(payload)

    normalized: dict[str, object] = {}
    for raw_key, value in payload.items():
        key = spec.aliases.get(str(raw_key), str(raw_key))
        if key in spec.payload_fields:
            normalized[key] = value

    for field_name in spec.payload_fields:
        normalized.setdefault(field_name, _empty_value_for_field(field_name))
    return normalized


def missing_required_fields(capability_id: CapabilityId, payload: dict[str, object]) -> list[str]:
    """Return missing fields after schema normalization."""
    spec = get_capability_spec(capability_id)
    if spec is None:
        return []
    return [field for field in spec.required_fields if _is_empty(payload.get(field))]


def missing_execution_fields(capability_id: CapabilityId, payload: dict[str, object]) -> list[str]:
    """Return fields needed to execute the capability, including one-of groups."""
    spec = get_capability_spec(capability_id)
    if spec is None:
        return []

    missing = missing_required_fields(capability_id, payload)
    for representative_field, field_group in spec.required_field_groups:
        if all(_is_empty(payload.get(field_name)) for field_name in field_group):
            missing.append(representative_field)
    return _dedupe(missing)


def _empty_value_for_field(field_name: str) -> object:
    if field_name.endswith("_hints") or field_name in {"attendees", "attachments", "cc"}:
        return []
    if field_name == "record":
        return {}
    if field_name == "limit":
        return 20
    return ""


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
