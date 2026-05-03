import asyncio
import json

import pytest

from app.domain.enums import CapabilityId, IntentType
from app.services.intent_service import IntentService


CASES = [
    ("回复上一条消息：收到", {"capability_id": "im.messages_reply", "payload": {"text": "收到", "message_hint": "上一条消息"}}, CapabilityId.IM_MESSAGES_REPLY, {"text": "收到"}),
    ("搜索项目群里关于发布的消息", {"capability_id": "im.messages_search", "payload": {"query": "发布", "chat_hint": "项目群"}}, CapabilityId.IM_MESSAGES_SEARCH, {"query": "发布"}),
    ("列出项目群最近的聊天记录", {"capability_id": "im.chat_messages_list", "payload": {"chat_hint": "项目群", "limit": 10}}, CapabilityId.IM_CHAT_MESSAGES_LIST, {"limit": 10}),
    ("搜索群项目组", {"capability_id": "im.chat_search", "payload": {"query": "项目组"}}, CapabilityId.IM_CHAT_SEARCH, {"query": "项目组"}),
    ("创建群，标题叫发布小组", {"capability_id": "im.chat_create", "payload": {"name": "发布小组", "description": "发布同步群"}}, CapabilityId.IM_CHAT_CREATE, {"name": "发布小组"}),
    ("安排会议，标题叫项目复盘，明天下午三点", {"capability_id": "calendar.create", "payload": {"title": "项目复盘", "start_time": "2026-05-01T15:00:00+08:00", "end_time": "2026-05-01T16:00:00+08:00"}}, CapabilityId.CALENDAR_CREATE, {"title": "项目复盘"}),
    ("把明天下午三点的会议改到四点", {"capability_id": "calendar.reschedule", "payload": {"event_hint": "项目复盘", "target_time": "2026-05-01T16:00:00+08:00"}}, CapabilityId.CALENDAR_RESCHEDULE, {"event_hint": "项目复盘"}),
    ("查看今天日程", {"capability_id": "calendar.agenda", "payload": {"time_range": "今天"}}, CapabilityId.CALENDAR_AGENDA, {"time_range": "今天"}),
    ("查询梅家济明天下午忙闲", {"capability_id": "calendar.freebusy", "payload": {"time_range": "明天下午", "user_hints": ["梅家济"]}}, CapabilityId.CALENDAR_FREEBUSY, {"time_range": "明天下午"}),
    ("创建文档，标题叫项目复盘", {"capability_id": "docs.create", "payload": {"title": "项目复盘", "content": "复盘提纲"}}, CapabilityId.DOC_CREATE, {"title": "项目复盘"}),
    ("更新文档项目复盘：补充风险列表", {"capability_id": "docs.update", "payload": {"title": "项目复盘", "content": "补充风险列表"}}, CapabilityId.DOC_UPDATE, {"content": "补充风险列表"}),
    ("搜索文档项目复盘", {"capability_id": "docs.search", "payload": {"query": "项目复盘"}}, CapabilityId.DOC_SEARCH, {"query": "项目复盘"}),
    ("把表格A1更新为hello", {"capability_id": "sheets.update", "payload": {"cell": "A1", "value": "hello"}}, CapabilityId.SHEET_UPDATE, {"cell": "A1", "value": "hello"}),
    ("读取表格A1", {"capability_id": "sheets.read", "payload": {"cell": "A1"}}, CapabilityId.SHEET_READ, {"cell": "A1"}),
    ("搜索联系人梅家济", {"capability_id": "contact.search", "payload": {"query": "梅家济"}}, CapabilityId.CONTACT_SEARCH, {"query": "梅家济"}),
    ("创建任务：完成演示脚本", {"capability_id": "task.create", "payload": {"title": "完成演示脚本"}}, CapabilityId.TASK_CREATE, {"title": "完成演示脚本"}),
    ("发邮件给梅家济：今天进度已完成", {"capability_id": "mail.send", "payload": {"subject": "进度同步", "body": "今天进度已完成", "to_hints": ["梅家济"]}}, CapabilityId.MAIL_SEND, {"body": "今天进度已完成"}),
    ("给多维表格新增记录：状态=完成", {"capability_id": "base.record_create", "payload": {"record": {"status": "完成"}}}, CapabilityId.BASE_RECORD_CREATE, {"record": {"status": "完成"}}),
]


@pytest.mark.parametrize(("message", "llm_payload", "capability_id", "expected_payload"), CASES)
def test_llm_contract_maps_main_capabilities(
    message: str,
    llm_payload: dict[str, object],
    capability_id: CapabilityId,
    expected_payload: dict[str, object],
) -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_require_llm = True

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        return dict(kwargs["payload"])

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        response = {
            "reason": "parsed by qwen",
            "action_plan": ["parse request", "return structured payload"],
            "missing_fields": [],
        }
        response.update(llm_payload)
        return json.dumps(response, ensure_ascii=False), None

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse(message))

    assert decision.standard_action.capability_id == capability_id
    for key, value in expected_payload.items():
        assert decision.standard_action.payload.get(key) == value


def test_llm_contract_supports_message_then_docs_sequence() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_require_llm = True

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "梅家济":
            payload["user_id"] = "ou_mei"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "reason": "plan the user request in order",
                    "action_plan": ["send reminder", "create follow-up doc"],
                    "tasks": [
                        {
                            "raw_message": "跟梅家济说注意群里的消息",
                            "capability_id": "im.message_send",
                            "reason": "send the reminder first",
                            "action_plan": ["resolve target", "send message"],
                            "payload": {"chat_hint": "梅家济", "text": "注意群里的消息"},
                            "missing_fields": [],
                        },
                        {
                            "raw_message": "然后创建文档《小组消息跟进》",
                            "capability_id": "docs.create",
                            "reason": "create the follow-up doc",
                            "action_plan": ["draft title", "create doc"],
                            "payload": {"title": "小组消息跟进", "content": ""},
                            "missing_fields": [],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("跟梅家济说注意群里的消息，然后创建文档《小组消息跟进》"))

    assert decision.intent_type == IntentType.MULTI_TASK
    assert decision.parse_source == "qwen_multi_plan"
    assert decision.task_clauses == ["跟梅家济说注意群里的消息", "然后创建文档《小组消息跟进》"]
    assert decision.planned_actions[0].capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.planned_actions[0].payload["user_id"] == "ou_mei"
    assert decision.planned_actions[1].capability_id == CapabilityId.DOC_CREATE
    assert decision.planned_actions[1].payload["title"] == "小组消息跟进"
