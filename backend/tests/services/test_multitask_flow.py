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
        "跟梅家济说注意群里的消息；"
        "然后创建文档《小组消息跟进》；"
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
                        "raw_message": "跟梅家济说注意群里的消息",
                        "capability_id": "im.message_send",
                        "reason": "send the reminder first",
                        "action_plan": ["resolve recipient", "send message"],
                        "payload": {"chat_hint": "梅家济", "text": "注意群里的消息"},
                        "missing_fields": [],
                    },
                    {
                        "raw_message": "然后创建文档《小组消息跟进》",
                        "capability_id": "docs.create",
                        "reason": "create the follow-up doc",
                        "action_plan": ["draft title", "create doc"],
                        "payload": {"title": "小组消息跟进", "content": "记录群消息重点"},
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
        if payload.get("chat_hint") == "梅家济":
            payload["user_id"] = "ou_mei"
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
        "跟梅家济说注意群里的消息",
        "然后创建文档《小组消息跟进》",
        "安排明天下午三点到四点的发布复盘会议",
        "把表格A1更新为已发布",
    ]
    assert [item.capability_id for item in decision.planned_actions] == [
        CapabilityId.IM_MESSAGE_SEND,
        CapabilityId.DOC_CREATE,
        CapabilityId.CALENDAR_CREATE,
        CapabilityId.SHEET_UPDATE,
    ]
    assert decision.planned_actions[0].payload["user_id"] == "ou_mei"
    assert decision.planned_actions[0].payload["text"] == "注意群里的消息"
    assert decision.structured_command["tasks"][1]["capability_id"] == "docs.create"
    assert decision.structured_command["tasks"][2]["payload"]["title"] == "发布复盘会议"
    assert decision.structured_command["tasks"][3]["payload"]["cell"] == "A1"


def test_orchestrator_executes_message_and_docs_and_keeps_other_domains_structured_only() -> None:
    service = OrchestratorService()
    service.intent_service.settings.dashscope_api_key = "test-key"
    service.intent_service.settings.intent_require_llm = True
    responses = _responses()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "梅家济":
            payload["user_id"] = "ou_mei"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    execute_calls: list[CapabilityId] = []

    def fake_execute_action(*_: object, **kwargs: object) -> ExecutorResult:
        action = kwargs["action"]
        assert hasattr(action, "capability_id")
        execute_calls.append(action.capability_id)
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={
                "domain": "message" if action.capability_id == CapabilityId.IM_MESSAGE_SEND else "doc_sheet",
                "dry_run": False,
                "steps": [{"exit_code": 0}],
                "error": None,
            },
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
        "completed",
        "plan_only",
        "plan_only",
    ]
    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.execution_payload["mode"] == "multi_task"
    assert response.execution_payload["completed_count"] == 2
    assert response.execution_payload["plan_only_count"] == 2
    assert execute_calls == [CapabilityId.IM_MESSAGE_SEND, CapabilityId.DOC_CREATE]
    assert response.planned_actions[0].execution_payload["steps"][0]["exit_code"] == 0
    assert response.planned_actions[1].execution_payload["steps"][0]["exit_code"] == 0
    assert response.planned_actions[2].standard_action.payload["start_time"] == "2026-05-03T15:00:00+08:00"
    assert response.planned_actions[3].standard_action.payload["value"] == "已发布"
    assert task is not None
    assert [step.name for step in task.steps] == [
        "task_created",
        "intent_parsed",
        "action_1_cli_started",
        "action_1_cli_finished",
        "action_2_cli_started",
        "action_2_cli_finished",
        "action_3_planned_only",
        "action_4_planned_only",
    ]


def test_orchestrator_multitask_runs_real_message_and_docs_cli_path() -> None:
    service = OrchestratorService()
    service.intent_service.settings.dashscope_api_key = "test-key"
    service.intent_service.settings.intent_require_llm = True
    responses = _responses()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        if payload.get("chat_hint") == "梅家济":
            payload["user_id"] = "ou_mei"
            payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    captured_argvs: list[list[str]] = []

    def fake_run(argv: list[str], *_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        captured_argvs.append(list(argv))
        stdout = b'{"ok":true,"message_id":"om_123"}'
        if len(captured_argvs) == 2:
            stdout = b'{"ok":true,"document":{"document_id":"doccn123","url":"https://example/doccn123"}}'
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=stdout,
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
    assert response.execution_payload["completed_count"] == 2
    assert response.execution_payload["plan_only_count"] == 2
    assert len(captured_argvs) == 2
    assert Path(captured_argvs[0][0]).name.lower() in {"lark-cli", "lark-cli.cmd"}
    assert captured_argvs[0][1:3] == ["im", "+messages-send"]
    assert "--user-id" in captured_argvs[0]
    assert "ou_mei" in captured_argvs[0]
    assert "--text" in captured_argvs[0]
    assert "注意群里的消息" in captured_argvs[0]
    assert "--idempotency-key" in captured_argvs[0]
    assert captured_argvs[1][1:3] == ["docs", "+create"]
    assert "--title" in captured_argvs[1]
    assert "小组消息跟进" in captured_argvs[1]
    assert "--markdown" in captured_argvs[1]
    assert "记录群消息重点" in captured_argvs[1]
    first_step = response.planned_actions[0].execution_payload["steps"][0]
    assert "im +messages-send" in first_step["command"]
    assert "--user-id ou_mei" in first_step["command"]
    assert first_step["parsed"]["message_id"] == "om_123"
    second_step = response.planned_actions[1].execution_payload["steps"][0]
    assert "docs +create" in second_step["command"]
    assert second_step["parsed"]["document"]["document_id"] == "doccn123"
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

    captured_argvs: list[list[str]] = []

    def fake_run(argv: list[str], *_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        captured_argvs.append(list(argv))
        stdout = b'{"ok":true}'
        if len(captured_argvs) == 2:
            stdout = b'{"ok":true,"document":{"document_id":"doccn456"}}'
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr=b"")

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
    assert len(captured_argvs) == 2
    assert Path(captured_argvs[0][0]).name.lower() in {"lark-cli", "lark-cli.cmd"}
    assert captured_argvs[0][1:3] == ["im", "+messages-send"]
    assert "--user-id" in captured_argvs[0]
    assert "ou_a" in captured_argvs[0]
    assert captured_argvs[1][1:3] == ["docs", "+create"]
    assert "--title" in captured_argvs[1]
    assert "发布说明" in captured_argvs[1]
    assert [item.status for item in resumed_response.planned_actions] == ["completed", "completed"]
    assert resumed_response.planned_actions[0].standard_action.payload["user_id"] == "ou_a"
    assert resumed_response.planned_actions[1].execution_payload["steps"][0]["exit_code"] == 0
