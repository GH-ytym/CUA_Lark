"""Smoke test for local recipient resolution in message intent flow."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.intent_service import IntentService


async def run() -> None:
    service = IntentService()
    cases = [
        "跟梅家济说hello",
        "给刘海俊发送：请确认今天的日报",
        "发送消息给小组：今晚十点发布",
        "在小组里发 今晚十点同步",
        "给王莹说下周一评审改到下午三点",
        "发消息给张三：你在吗",
        "跟李雷说“文档我已经更新了”",
        "帮我给梅家济发消息：下午开会",
        "给研发群发：版本已上线",
        "请给赵敏说一声我晚点到",
        "在项目群里说一下明天十点站会",
    ]
    output: dict[str, object] = {}
    stats = {
        "total": len(cases),
        "message_send": 0,
        "resolved_target": 0,
        "non_empty_text": 0,
    }
    for text in cases:
        decision = await service.parse(message=text)
        payload = decision.structured_command.get("payload", {})
        if decision.intent_type.value == "message_send":
            stats["message_send"] += 1
        if isinstance(payload, dict) and (payload.get("chat_id") or payload.get("user_id")):
            stats["resolved_target"] += 1
        if isinstance(payload, dict) and str(payload.get("text", "")).strip():
            stats["non_empty_text"] += 1
        output[text] = {
            "parse_source": decision.parse_source,
            "intent_type": decision.intent_type.value,
            "payload": payload,
        }
    print(json.dumps({"stats": stats, "cases": output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
