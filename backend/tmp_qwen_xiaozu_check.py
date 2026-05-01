import asyncio, json, os
from app.services.intent_service import IntentService
from app.services.lark_cli_service import LarkCliService

os.environ["DASHSCOPE_API_KEY"] = "sk-eae95168f2e7491c8d77b6a79ec1bffd"

CASES = [
    ("?????????CI ?????????????", "im.message_send"),
    ("?????????? 9 ???????????", "im.message_send"),
    ("????????????", "im.messages_search"),
    ("???????????", "im.chat_messages_list"),
]

async def main():
    service = IntentService()
    cli = LarkCliService()
    rows = []
    for message, expected in CASES:
        decision = await service.parse(message)
        action = decision.standard_action.model_copy(update={"payload": dict(decision.standard_action.payload) | {"dry_run": True}})
        result = cli.execute_action(action=action, dry_run=True)
        rows.append({
            "message": message,
            "expected": expected,
            "parse_source": decision.parse_source,
            "capability_id": decision.standard_action.capability_id.value,
            "payload": decision.standard_action.payload,
            "cli_success": result.success,
            "cli_summary": result.summary,
            "cli_error": result.payload.get("error"),
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))

asyncio.run(main())
