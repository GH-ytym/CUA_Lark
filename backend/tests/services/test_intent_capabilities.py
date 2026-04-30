import asyncio

import pytest

from app.domain.enums import CapabilityId
from app.services.intent_service import IntentService


CASES = [
    ("给梅家济发消息：hello", CapabilityId.IM_MESSAGE_SEND, {"chat_hint": "梅家济", "text": "hello"}),
    ("回复上一条消息：收到", CapabilityId.IM_MESSAGES_REPLY, {"text": "收到"}),
    ("搜索项目群里关于发布的消息", CapabilityId.IM_MESSAGES_SEARCH, {"query": "发布"}),
    ("列出项目群最近的聊天记录", CapabilityId.IM_CHAT_MESSAGES_LIST, {"limit": 20}),
    ("搜索群项目组", CapabilityId.IM_CHAT_SEARCH, {"query": "群项目组"}),
    ("创建群，标题叫发布小组", CapabilityId.IM_CHAT_CREATE, {"name": "发布小组"}),
    ("安排会议，标题叫项目复盘，明天下午三点", CapabilityId.CALENDAR_CREATE, {"title": "项目复盘"}),
    ("把明天下午三点的会议改到四点", CapabilityId.CALENDAR_RESCHEDULE, {"event_hint": "把明天下午三点的"}),
    ("查看今天日程", CapabilityId.CALENDAR_AGENDA, {"time_range": "今天"}),
    ("查询梅家济明天下午忙闲", CapabilityId.CALENDAR_FREEBUSY, {"time_range": "明天"}),
    ("创建文档，标题叫项目复盘", CapabilityId.DOC_CREATE, {"title": "项目复盘"}),
    ("更新文档项目复盘：补充风险列表", CapabilityId.DOC_UPDATE, {"content": "补充风险列表"}),
    ("搜索文档项目复盘", CapabilityId.DOC_SEARCH, {"query": "文档项目复盘"}),
    ("把表格A1更新为hello", CapabilityId.SHEET_UPDATE, {"cell": "A1", "value": "hello"}),
    ("读取表格A1", CapabilityId.SHEET_READ, {"cell": "A1"}),
    ("搜索联系人梅家济", CapabilityId.CONTACT_SEARCH, {"query": "联系人梅家济"}),
    ("创建任务：完成演示脚本", CapabilityId.TASK_CREATE, {"title": "完成演示脚本"}),
    ("发邮件给梅家济：今天进度已完成", CapabilityId.MAIL_SEND, {"body": "今天进度已完成"}),
    ("给多维表格新增记录：状态=完成", CapabilityId.BASE_RECORD_CREATE, {"record": {"raw": "给多维表格新增记录：状态=完成"}}),
]


@pytest.mark.parametrize(("message", "capability_id", "expected_payload"), CASES)
def test_rule_parser_maps_main_capabilities(
    message: str,
    capability_id: CapabilityId,
    expected_payload: dict[str, object],
) -> None:
    service = IntentService()
    service.settings.minimax_api_key = ""
    service.settings.intent_message_fastpath_enabled = True

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    decision = asyncio.run(service.parse(message))

    assert decision.standard_action.capability_id == capability_id
    for key, value in expected_payload.items():
        assert decision.standard_action.payload.get(key) == value
