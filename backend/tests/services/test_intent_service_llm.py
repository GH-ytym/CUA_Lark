import asyncio
import json

from app.services.intent_service import IntentService


def test_llm_two_stage_message_parse() -> None:
    service = IntentService()
    service.settings.minimax_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    responses = [
        json.dumps(
            {
                "intent_type": "message_send",
                "reason": "用户要发消息",
                "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                "entities": {"chat_hint": "梅家济", "chat_id": "", "user_id": "", "message_text": "hello"},
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {"chat_hint": "梅家济", "chat_id": "", "user_id": "", "message_text": "hello"},
            ensure_ascii=False,
        ),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "minimax"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"


def test_llm_skips_second_stage_when_entities_complete() -> None:
    service = IntentService()
    service.settings.minimax_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    call_count = {"n": 0}

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        call_count["n"] += 1
        return (
            json.dumps(
                {
                    "intent_type": "message_send",
                    "reason": "用户要发消息",
                    "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                    "entities": {"chat_hint": "梅家济", "chat_id": "", "user_id": "", "message_text": "hello"},
                },
                ensure_ascii=False,
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "minimax"
    assert payload.get("text") == "hello"
    assert call_count["n"] == 1


def test_llm_accepts_legacy_action_format() -> None:
    service = IntentService()
    service.settings.minimax_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    responses = [
        json.dumps({"action": "greeting", "target": "梅家济", "message": "hello"}, ensure_ascii=False),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "minimax"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"


def test_llm_json_repair_path() -> None:
    service = IntentService()
    service.settings.minimax_api_key = "test-key"

    responses = [
        "<think>not json</think>",
        json.dumps(
            {
                "intent_type": "doc_create",
                "reason": "用户要创建文档",
                "action_plan": ["确认主题", "创建文档"],
                "entities": {},
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("帮我创建一个文档"))
    assert decision.parse_source == "minimax"
    assert decision.intent_type.value == "doc_create"


def test_message_fastpath_without_llm() -> None:
    service = IntentService()
    service.settings.minimax_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = True

    async def should_not_call(*_: object, **__: object) -> tuple[str, str | None]:
        raise AssertionError("LLM should not be called for message fastpath")

    service._chat_completion = should_not_call  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "rules_fastpath"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"
