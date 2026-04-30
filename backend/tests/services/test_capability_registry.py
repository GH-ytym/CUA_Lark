from app.domain.capability_registry import missing_required_fields, normalize_payload
from app.domain.enums import CapabilityId


def test_message_send_payload_aliases_are_normalized() -> None:
    payload = normalize_payload(
        CapabilityId.IM_MESSAGE_SEND,
        {"target": "项目群", "message_text": "今晚发布"},
    )

    assert payload["chat_hint"] == "项目群"
    assert payload["text"] == "今晚发布"
    assert payload["chat_id"] == ""
    assert missing_required_fields(CapabilityId.IM_MESSAGE_SEND, payload) == []


def test_message_search_payload_aliases_are_normalized() -> None:
    payload = normalize_payload(CapabilityId.IM_MESSAGES_SEARCH, {"keyword": "发布"})

    assert payload["query"] == "发布"
    assert payload["chat_id"] == ""
    assert missing_required_fields(CapabilityId.IM_MESSAGES_SEARCH, payload) == []


def test_message_reply_requires_text_and_target_message() -> None:
    payload = normalize_payload(CapabilityId.IM_MESSAGES_REPLY, {"content": "收到"})

    assert payload["text"] == "收到"
    assert payload["message_id"] == ""
    assert missing_required_fields(CapabilityId.IM_MESSAGES_REPLY, payload) == []
