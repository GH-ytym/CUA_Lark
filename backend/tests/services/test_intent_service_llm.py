import asyncio
import json
from zoneinfo import ZoneInfoNotFoundError

from app.domain.enums import CapabilityId, ExecutorType, IntentType
from app.services import intent_service as intent_service_module
from app.services.intent_service import IntentService
from shared.error_codes import UnifiedErrorCode


def _make_service() -> IntentService:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_require_llm = True
    return service


def test_llm_message_send_structures_payload_and_runs_resolver() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["chat_id"] = "oc_proj"
        payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "user wants to send a message",
                    "action_plan": ["resolve recipient", "send message"],
                    "payload": {"chat_hint": "项目群", "text": "今晚九点发布"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("跟项目群说今晚九点发布"))

    assert decision.parse_source == "qwen_plan"
    assert decision.intent_type == IntentType.MESSAGE_SEND
    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.executor_hint == ExecutorType.CLI
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["text"] == "今晚九点发布"
    assert decision.raw_llm_payload["capability_id"] == "im.message_send"


def test_llm_structured_error_code_is_preserved_on_standard_action() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "t": [
                        {
                            "m": "给刚刚那个人发消息：hello",
                            "c": "im.message_send",
                            "p": {"chat_hint": "刚刚那个人", "text": "hello"},
                            "miss": ["chat_hint"],
                            "ec": int(UnifiedErrorCode.HANDOFF_REQUIRED),
                            "er": "needs recent Feishu UI context",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("给刚刚那个人发消息：hello"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.handoff_error_code == int(UnifiedErrorCode.HANDOFF_REQUIRED)
    assert decision.standard_action.handoff_reason == "needs recent Feishu UI context"
    assert decision.structured_command["payload"]["chat_hint"] == "刚刚那个人"


def test_llm_message_search_structures_payload() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["chat_id"] = "oc_proj"
        payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.messages_search",
                    "reason": "search messages in one chat",
                    "action_plan": ["resolve chat", "search messages"],
                    "payload": {"chat_hint": "项目群", "query": "发布"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("搜索项目群里关于发布的消息"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGES_SEARCH
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["query"] == "发布"
    assert decision.standard_action.payload["identity"] == "user"


def test_llm_json_repair_path() -> None:
    service = _make_service()

    responses = [
        "<think>not json</think>",
        json.dumps(
            {
                "capability_id": "docs.create",
                "reason": "create a doc",
                "action_plan": ["draft title", "create doc"],
                "payload": {"title": "项目复盘"},
                "missing_fields": [],
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("帮我创建一个项目复盘文档"))

    assert decision.parse_source == "qwen_plan"
    assert decision.standard_action.capability_id == CapabilityId.DOC_CREATE
    assert decision.standard_action.payload["title"] == "项目复盘"


def test_unknown_capability_stays_unknown() -> None:
    service = _make_service()

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "unknown",
                    "reason": "cannot determine the task",
                    "action_plan": ["ask for clarification"],
                    "payload": {},
                    "missing_fields": [],
                }
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("帮我处理一下"))

    assert decision.intent_type == IntentType.UNKNOWN
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN
    assert decision.selected_executor == ExecutorType.NONE


def test_missing_fields_are_preserved_without_rule_guessing() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        return dict(kwargs["payload"])

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "target is missing",
                    "action_plan": ["ask user for recipient"],
                    "payload": {"chat_hint": "", "text": "今晚九点发布"},
                    "missing_fields": ["chat_hint"],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("发个今晚九点发布"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.payload["text"] == "今晚九点发布"
    assert decision.missing_fields == ["chat_hint"]


def test_calendar_create_is_structured_by_llm() -> None:
    service = _make_service()

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "calendar.create",
                    "reason": "create a meeting",
                    "action_plan": ["confirm time", "create event"],
                    "payload": {
                        "title": "项目复盘",
                        "start_time": "2026-05-01T15:00:00+08:00",
                        "end_time": "2026-05-01T16:00:00+08:00",
                        "attendees": ["张三"],
                        "location": "会议室A",
                    },
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("安排今天下午三点到四点的项目复盘会议"))

    assert decision.standard_action.capability_id == CapabilityId.CALENDAR_CREATE
    assert decision.standard_action.payload["title"] == "项目复盘"
    assert decision.standard_action.payload["attendees"] == ["张三"]


def test_llm_compact_plan_contract_is_supported() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "项目群":
            payload["chat_id"] = "oc_proj"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "r": "plan the release workflow",
                    "a": ["send release notice", "create recap doc"],
                    "t": [
                        {
                            "m": "先给项目群发消息：今晚九点发布",
                            "c": "im.message_send",
                            "r": "send the message",
                            "a": ["resolve target", "send"],
                            "p": {"chat_hint": "项目群", "text": "今晚九点发布"},
                            "miss": [],
                        },
                        {
                            "m": "然后创建文档，标题叫发布复盘",
                            "c": "docs.create",
                            "r": "create the doc",
                            "a": ["draft title", "create doc"],
                            "p": {"title": "发布复盘", "content": "复盘提纲"},
                            "miss": [],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("先给项目群发消息：今晚九点发布；然后创建文档，标题叫发布复盘"))

    assert decision.intent_type == IntentType.MULTI_TASK
    assert decision.parse_source == "qwen_multi_plan"
    assert decision.task_clauses == ["先给项目群发消息：今晚九点发布", "然后创建文档，标题叫发布复盘"]
    assert decision.planned_actions[0].capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.planned_actions[0].payload["chat_id"] == "oc_proj"
    assert decision.planned_actions[1].capability_id == CapabilityId.DOC_CREATE
    assert decision.structured_command["tasks"][1]["payload"]["title"] == "发布复盘"


def test_llm_minimal_plan_contract_outputs_three_ordered_tasks() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "梅家济":
            payload["user_id"] = "ou_mei"
            payload["resolution_status"] = "resolved"
        elif payload.get("chat_hint") == "小组群":
            payload["chat_id"] = "oc_group"
            payload["resolution_status"] = "resolved"
        elif payload.get("chat_hint") == "刘海俊":
            payload["user_id"] = "ou_liu"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "t": [
                        {
                            "m": "给梅家济发消息：hello",
                            "c": "im.message_send",
                            "p": {"chat_hint": "梅家济", "text": "hello"},
                        },
                        {
                            "m": "在小组群里说你好",
                            "c": "im.message_send",
                            "p": {"chat_hint": "小组群", "text": "你好"},
                        },
                        {
                            "m": "查找刘海俊的聊天记录",
                            "c": "im.chat_messages_list",
                            "p": {"chat_hint": "刘海俊"},
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("给梅家济发消息：hello，在小组群里说你好，然后查找刘海俊的聊天记录"))

    assert decision.intent_type == IntentType.MULTI_TASK
    assert decision.parse_source == "qwen_multi_plan"
    assert decision.task_clauses == ["给梅家济发消息：hello", "在小组群里说你好", "查找刘海俊的聊天记录"]
    assert [item.capability_id for item in decision.planned_actions] == [
        CapabilityId.IM_MESSAGE_SEND,
        CapabilityId.IM_MESSAGE_SEND,
        CapabilityId.IM_CHAT_MESSAGES_LIST,
    ]
    assert decision.planned_actions[0].payload["user_id"] == "ou_mei"
    assert decision.planned_actions[0].payload["text"] == "hello"
    assert decision.planned_actions[1].payload["chat_id"] == "oc_group"
    assert decision.planned_actions[1].payload["text"] == "你好"
    assert decision.planned_actions[2].payload["user_id"] == "ou_liu"
    assert decision.structured_command["tasks"][2]["capability_id"] == "im.chat_messages_list"


def test_llm_unavailable_returns_unknown() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""

    decision = asyncio.run(service.parse("跟项目群说今晚九点发布"))

    assert decision.parse_source == "llm_unavailable"
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN


def test_current_time_hint_falls_back_when_tzdata_is_missing(monkeypatch) -> None:
    def fake_zone_info(_: str) -> object:
        raise ZoneInfoNotFoundError("No time zone found with key Asia/Shanghai")

    monkeypatch.setattr(intent_service_module, "ZoneInfo", fake_zone_info)

    current_time = IntentService._current_time_hint()

    assert current_time.endswith("+08:00")


def test_invalid_first_plan_triggers_authoritative_reask() -> None:
    service = _make_service()
    prompts: list[str] = []
    responses = [
        json.dumps(
            {
                "t": [
                    {
                        "m": "send update",
                        "c": "not.registered",
                        "p": {"text": "ready"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "t": [
                    {
                        "m": "send update",
                        "c": "im.message_send",
                        "p": {"chat_hint": "Alex", "text": "ready"},
                        "miss": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["user_id"] = "ou_alex"
        return payload

    async def fake_chat_completion(system_prompt: str, *_: object, **__: object) -> tuple[str, str | None]:
        prompts.append(system_prompt)
        return responses.pop(0), None

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("send Alex: ready"))

    assert decision.parse_source == "qwen_authoritative_reask"
    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.payload["user_id"] == "ou_alex"
    assert "authoritative validator" in prompts[1]


def test_payload_fields_outside_registry_schema_trigger_authoritative_reask() -> None:
    service = _make_service()
    responses = [
        json.dumps(
            {
                "t": [
                    {
                        "m": "send update",
                        "c": "im.message_send",
                        "p": {"chat_hint": "Alex", "text": "ready", "unsupported": "drop me"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "t": [
                    {
                        "m": "send update",
                        "c": "im.message_send",
                        "p": {"chat_hint": "Alex", "text": "ready"},
                        "miss": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        return dict(kwargs["payload"])

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("send Alex: ready"))

    assert decision.parse_source == "qwen_authoritative_reask"
    assert "unsupported" not in decision.standard_action.payload
    assert decision.standard_action.payload["chat_hint"] == "Alex"


def test_missing_task_payload_is_repaired_by_llm_without_rule_guessing() -> None:
    service = _make_service()
    payloads: list[dict[str, object]] = []
    responses = [
        json.dumps(
            {
                "t": [
                    {
                        "m": "send update to Alex",
                        "c": "im.message_send",
                        "p": {"chat_hint": "", "text": "ready"},
                        "miss": ["chat_hint"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "c": "im.message_send",
                "p": {"chat_hint": "Alex", "text": "ready"},
                "miss": [],
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "Alex":
            payload["user_id"] = "ou_alex"
        return payload

    async def fake_chat_completion(*_: object, **kwargs: object) -> tuple[str, str | None]:
        user_payload = kwargs.get("user_payload")
        if isinstance(user_payload, dict):
            payloads.append(user_payload)
        return responses.pop(0), None

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("send update to Alex: ready"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.payload["chat_hint"] == "Alex"
    assert decision.standard_action.payload["user_id"] == "ou_alex"
    assert decision.missing_fields == []
    assert payloads[1]["missing_fields"] == ["chat_hint"]
    assert payloads[1]["capability_schema"]["capability_id"] == "im.message_send"
