import asyncio
import json
from pathlib import Path
import subprocess

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult
from app.schemas.chat import ExecuteCommandRequest
from app.services.intent_service import IntentService
from app.services.orchestrator import OrchestratorService


def _multitask_message() -> str:
    return (
        "先给项目群发消息：今晚九点发布；"
        "然后创建文档，标题叫发布复盘；"
        "再安排明天下午三点到四点的发布复盘会议；"
        "最后把表格A1更新为已发布"
    )


def _responses() -> list[str]:
    return [
        json.dumps(
            {
                "reason": "plan the full release workflow in order",
                "action_plan": ["send release notice", "create recap doc", "schedule recap meeting", "update sheet"],
                "tasks": [
                    {
                        "raw_message": "先给项目群发消息：今晚九点发布",
                        "capability_id": "im.message_send",
                        "reason": "send a release notice",
                        "action_plan": ["resolve recipient", "send message"],
                        "payload": {"chat_hint": "项目群", "text": "今晚九点发布"},
                        "missing_fields": [],
                    },
                    {
                        "raw_message": "创建文档，标题叫发布复盘",
                        "capability_id": "docs.create",
                        "reason": "create the recap doc",
                        "action_plan": ["draft title", "create doc"],
                        "payload": {"title": "发布复盘", "content": "复盘提纲"},
                        "missing_fields": [],
                    },
                    {
                        "raw_message": "安排明天下午三点到四点的发布复盘会议",
                        "capability_id": "calendar.create",
                        "reason": "schedule the recap meeting",
                        "action_plan": ["confirm time", "create event"],
                        "payload": {
                            "title": "发布复盘会议",
                            "start_time": "2026-05-03T15:00:00+08:00",
                            "end_time": "2026-05-03T16:00:00+08:00",
                            "attendees": ["项目群"],
                            "location": "会议室A",
                        },
                        "missing_fields": [],
                    },
                    {
                        "raw_message": "把表格A1更新为已发布",
                        "capability_id": "sheets.update",
                        "reason": "update one status cell",
                        "action_plan": ["locate cell", "write value"],
                        "payload": {"cell": "A1", "value": "已发布"},
                        "missing_fields": [],
                    },
                ],
            },
            ensure_ascii=False,
        )
    ]


def test_intent_service_splits_multitask_request_in_order() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_require_llm = True
    responses = _responses()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "项目群":
            payload["chat_id"] = "oc_proj"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse(_multitask_message()))

    assert decision.intent_type == IntentType.MULTI_TASK
    assert decision.parse_source == "qwen_multi_plan"
    assert decision.task_clauses == [
        "先给项目群发消息：今晚九点发布",
        "创建文档，标题叫发布复盘",
        "安排明天下午三点到四点的发布复盘会议",
        "把表格A1更新为已发布",
    ]
    assert [item.capability_id for item in decision.planned_actions] == [
        CapabilityId.IM_MESSAGE_SEND,
        CapabilityId.DOC_CREATE,
        CapabilityId.CALENDAR_CREATE,
        CapabilityId.SHEET_UPDATE,
    ]
    assert decision.planned_actions[0].payload["chat_id"] == "oc_proj"
    assert decision.planned_actions[0].payload["text"] == "今晚九点发布"
    assert decision.structured_command["tasks"][1]["capability_id"] == "docs.create"
    assert decision.structured_command["tasks"][2]["payload"]["title"] == "发布复盘会议"
    assert decision.structured_command["tasks"][3]["payload"]["cell"] == "A1"


def test_orchestrator_executes_message_and_keeps_other_domains_structured_only() -> None:
    service = OrchestratorService()
    service.intent_service.settings.dashscope_api_key = "test-key"
    service.intent_service.settings.intent_require_llm = True
    responses = _responses()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "项目群":
            payload["chat_id"] = "oc_proj"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "message", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        )

    service.intent_service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service.intent_service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(
        service.execute_command(
            ExecuteCommandRequest(
                message=_multitask_message(),
                session_id="s1",
                user_id="u1",
                conversation_type="chat",
                context_hint="",
            )
        )
    )
    task = service.get_task(response.task_id)

    assert response.parsed_intent == IntentType.MULTI_TASK
    assert [item.standard_action.capability_id for item in response.planned_actions] == [
        CapabilityId.IM_MESSAGE_SEND,
        CapabilityId.DOC_CREATE,
        CapabilityId.CALENDAR_CREATE,
        CapabilityId.SHEET_UPDATE,
    ]
    assert [item.status for item in response.planned_actions] == [
        "completed",
        "plan_only",
        "plan_only",
        "plan_only",
    ]
    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.execution_payload["mode"] == "multi_task"
    assert response.execution_payload["completed_count"] == 1
    assert response.execution_payload["plan_only_count"] == 3
    assert response.planned_actions[0].execution_payload["steps"][0]["exit_code"] == 0
    assert response.planned_actions[1].execution_payload["mode"] == "structured_only"
    assert response.planned_actions[2].standard_action.payload["start_time"] == "2026-05-03T15:00:00+08:00"
    assert response.planned_actions[3].standard_action.payload["value"] == "已发布"
    assert task is not None
    assert [step.name for step in task.steps] == [
        "task_created",
        "intent_parsed",
        "action_1_cli_started",
        "action_1_cli_finished",
        "action_2_planned_only",
        "action_3_planned_only",
        "action_4_planned_only",
    ]


def test_orchestrator_multitask_runs_real_message_cli_path() -> None:
    service = OrchestratorService()
    service.intent_service.settings.dashscope_api_key = "test-key"
    service.intent_service.settings.intent_require_llm = True
    responses = _responses()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "项目群":
            payload["chat_id"] = "oc_proj"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    captured_argv: list[str] = []

    def fake_run(argv: list[str], *_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        captured_argv[:] = list(argv)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=b'{"ok":true,"message_id":"om_123"}',
            stderr=b"",
        )

    service.intent_service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service.intent_service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    subprocess_run = subprocess.run
    try:
        subprocess.run = fake_run  # type: ignore[assignment]
        response = asyncio.run(
            service.execute_command(
                ExecuteCommandRequest(
                    message=_multitask_message(),
                    session_id="s1",
                    user_id="u1",
                    conversation_type="chat",
                    context_hint="",
                )
            )
        )
    finally:
        subprocess.run = subprocess_run  # type: ignore[assignment]

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.execution_payload["completed_count"] == 1
    assert response.execution_payload["plan_only_count"] == 3
    assert Path(captured_argv[0]).name.lower() in {"lark-cli", "lark-cli.cmd"}
    assert captured_argv[1:3] == ["im", "+messages-send"]
    assert "--chat-id" in captured_argv
    assert "oc_proj" in captured_argv
    assert "--text" in captured_argv
    assert "今晚九点发布" in captured_argv
    first_step = response.planned_actions[0].execution_payload["steps"][0]
    assert "im +messages-send" in first_step["command"]
    assert "--chat-id oc_proj" in first_step["command"]
    assert first_step["parsed"]["message_id"] == "om_123"
    assert response.planned_actions[1].execution_payload["payload"]["title"] == "发布复盘"
    assert response.planned_actions[2].execution_payload["payload"]["title"] == "发布复盘会议"
    assert response.planned_actions[3].execution_payload["payload"]["value"] == "已发布"


def test_multitask_confirmation_can_resume_message_action() -> None:
    service = OrchestratorService()
    service.intent_service.settings.dashscope_api_key = "test-key"
    service.intent_service.settings.intent_require_llm = True

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "王":
            payload["resolution_status"] = "needs_confirmation"
            payload["resolution_candidates"] = [
                {"name": "王建国", "entity_type": "contact", "entity_id": "ou_a", "score": 0.91},
                {"name": "王小明", "entity_type": "contact", "entity_id": "ou_b", "score": 0.88},
            ]
        return payload

    def response_batch() -> list[str]:
        return [
            json.dumps(
                {
                    "reason": "plan the message plus document workflow",
                    "action_plan": ["send confirmation", "create follow-up doc"],
                    "tasks": [
                        {
                            "raw_message": "先给王发消息：今晚九点发布",
                            "capability_id": "im.message_send",
                            "reason": "send a quick confirmation",
                            "action_plan": ["resolve recipient", "send message"],
                            "payload": {"chat_hint": "王", "text": "今晚九点发布"},
                            "missing_fields": [],
                        },
                        {
                            "raw_message": "然后创建文档，标题叫发布说明",
                            "capability_id": "docs.create",
                            "reason": "create a follow-up doc",
                            "action_plan": ["draft title", "create doc"],
                            "payload": {"title": "发布说明", "content": "记录发布结果"},
                            "missing_fields": [],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        ]

    responses = response_batch()

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service.intent_service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service.intent_service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    waiting_response = asyncio.run(
        service.execute_command(
            ExecuteCommandRequest(
                message="先给王发消息：今晚九点发布；然后创建文档，标题叫发布说明",
                session_id="s1",
                user_id="u1",
                conversation_type="chat",
                context_hint="",
            )
        )
    )

    assert waiting_response.parsed_intent == IntentType.MULTI_TASK
    assert waiting_response.needs_confirmation is True
    assert waiting_response.structured_payload["resolution_status"] == "needs_confirmation"
    assert waiting_response.resolution_candidates[0].entity_id == "ou_a"

    responses = response_batch()

    async def fake_chat_completion_resume(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    captured_argv: list[str] = []

    def fake_run(argv: list[str], *_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        captured_argv[:] = list(argv)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b'{"ok":true}', stderr=b"")

    service.intent_service._chat_completion = fake_chat_completion_resume  # type: ignore[method-assign]
    subprocess_run = subprocess.run
    try:
        subprocess.run = fake_run  # type: ignore[assignment]
        resumed_response = asyncio.run(
            service.execute_command(
                ExecuteCommandRequest(
                    message="先给王发消息：今晚九点发布；然后创建文档，标题叫发布说明",
                    session_id="s1",
                    user_id="u1",
                    conversation_type="chat",
                    context_hint="",
                    confirmed_entity_id="ou_a",
                )
            )
        )
    finally:
        subprocess.run = subprocess_run  # type: ignore[assignment]

    assert resumed_response.needs_confirmation is False
    assert resumed_response.structured_payload["user_id"] == "ou_a"
    assert resumed_response.structured_payload["resolution_method"] == "user_confirmation"
    assert Path(captured_argv[0]).name.lower() in {"lark-cli", "lark-cli.cmd"}
    assert captured_argv[1:3] == ["im", "+messages-send"]
    assert "--user-id" in captured_argv
    assert "ou_a" in captured_argv
    assert [item.status for item in resumed_response.planned_actions] == ["completed", "plan_only"]
    assert resumed_response.planned_actions[0].standard_action.payload["user_id"] == "ou_a"
    assert resumed_response.planned_actions[1].execution_payload["payload"]["title"] == "发布说明"
