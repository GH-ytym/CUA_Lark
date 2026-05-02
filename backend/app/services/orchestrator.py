"""Task orchestration from intent parsing through CLI execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import OrchestrationTask, StandardAction, TaskStep
from app.schemas.chat import ExecuteCommandRequest, ExecuteCommandResponse
from app.services.intent_service import IntentDecision, IntentService
from app.services.lark_cli_service import LarkCliService


class OrchestratorService:
    """Day-6 in-memory orchestrator for task creation and CLI execution."""

    def __init__(
        self,
        intent_service: IntentService | None = None,
        cli_service: LarkCliService | None = None,
    ) -> None:
        self.intent_service = intent_service or IntentService()
        self.cli_service = cli_service or LarkCliService()
        self._tasks: dict[str, OrchestrationTask] = {}

    async def execute_command(self, payload: ExecuteCommandRequest) -> ExecuteCommandResponse:
        """Create a task, parse it, optionally execute CLI, and return API ack."""
        task = OrchestrationTask(
            session_id=payload.session_id,
            user_id=payload.user_id,
            raw_message=payload.message,
        )
        self._record_step(task, "task_created", ExecutionStatus.QUEUED, "task accepted")

        parsed = await self.intent_service.parse(message=payload.message, context_hint=payload.context_hint)
        structured_payload = self._extract_payload(parsed)
        parsed, structured_payload = self._apply_confirmed_entity(
            parsed=parsed,
            structured_payload=structured_payload,
            confirmed_entity_id=payload.confirmed_entity_id,
        )

        action = self._standard_action_for(parsed=parsed, payload=structured_payload)
        task.intent_type = parsed.intent_type
        task.standard_action = action
        task.status = ExecutionStatus.PARSING
        task.updated_at = datetime.now(UTC)
        self._record_step(
            task,
            "intent_parsed",
            ExecutionStatus.PARSING,
            parsed.reason,
            {"capability_id": action.capability_id.value, "parse_source": parsed.parse_source},
        )

        needs_confirmation = self._needs_confirmation(parsed=parsed, payload=structured_payload)
        task.needs_confirmation = needs_confirmation
        confirmation_message = "请先确认要发送给谁，再继续执行。" if needs_confirmation else ""
        execution_status = ExecutionStatus.QUEUED
        execution_summary = "任务已受理，等待后续执行。"
        cli_error_code = ""
        cua_should_trigger = False
        execution_payload: dict[str, object] = {}

        if needs_confirmation:
            self._record_step(task, "confirmation_required", ExecutionStatus.QUEUED, confirmation_message)
        elif self._can_execute_cli(parsed) and self._is_cli_command_implemented(action):
            task.status = ExecutionStatus.CLI_RUNNING
            self._record_step(task, "cli_started", ExecutionStatus.CLI_RUNNING, action.capability_id.value)
            result = self.cli_service.execute_action(action=action, dry_run=False)
            task.executor_result = result
            execution_status = result.status
            execution_summary = result.summary
            execution_payload = result.payload
            cli_error_code = result.error_code
            cua_should_trigger = self._should_trigger_cua(cli_error_code)
            task.status = result.status
            self._record_step(
                task,
                "cli_finished",
                result.status,
                result.summary,
                {"error_code": cli_error_code, "cua_should_trigger": cua_should_trigger},
            )
        else:
            task.status = ExecutionStatus.FAILED if parsed.intent_type == IntentType.UNKNOWN else ExecutionStatus.CLI_FAILED
            execution_status = task.status
            if parsed.intent_type == IntentType.UNKNOWN:
                execution_summary = "未找到可执行的标准动作。"
            else:
                execution_summary = f"能力已解析但 CLI 命令尚未接入：{action.capability_id.value}"
                cli_error_code = LarkCliErrorCode.API_UNSUPPORTED.value
                cua_should_trigger = True
                execution_payload = {
                    "error": {
                        "code": cli_error_code,
                        "message": execution_summary,
                        "detail": {"capability_id": action.capability_id.value},
                    }
                }

        task.updated_at = datetime.now(UTC)
        self._tasks[task.task_id] = task

        return ExecuteCommandResponse(
            task_id=task.task_id,
            initial_status=ExecutionStatus.QUEUED,
            selected_executor=parsed.selected_executor,
            parsed_intent=parsed.intent_type,
            intent_reason=parsed.reason,
            action_plan=parsed.action_plan,
            parse_source=parsed.parse_source,
            standard_action=action,
            structured_payload=structured_payload,
            needs_confirmation=needs_confirmation,
            confirmation_message=confirmation_message,
            resolution_candidates=structured_payload.get("resolution_candidates", []),
            execution_status=execution_status,
            execution_summary=execution_summary,
            cli_error_code=cli_error_code,
            cua_should_trigger=cua_should_trigger,
            execution_payload=execution_payload,
            accepted_at=task.created_at,
        )

    def get_task(self, task_id: str) -> OrchestrationTask | None:
        """Return an in-memory task record by ID."""
        return self._tasks.get(task_id)

    @staticmethod
    def _extract_payload(parsed: IntentDecision) -> dict[str, object]:
        structured = parsed.structured_command if isinstance(parsed.structured_command, dict) else {}
        payload = structured.get("payload")
        return dict(payload) if isinstance(payload, dict) else dict(parsed.standard_action.payload)

    @staticmethod
    def _standard_action_for(parsed: IntentDecision, payload: dict[str, object]) -> StandardAction:
        action = parsed.standard_action
        if action.capability_id == CapabilityId.UNKNOWN and parsed.intent_type != IntentType.UNKNOWN:
            action = StandardAction(
                capability_id=OrchestratorService._capability_for_intent(parsed.intent_type),
                payload=payload,
                executor_hint=parsed.selected_executor,
                intent_type=parsed.intent_type,
            )
        return action.model_copy(update={"payload": payload})

    @staticmethod
    def _capability_for_intent(intent: IntentType) -> CapabilityId:
        mapping = {
            IntentType.MESSAGE_SEND: CapabilityId.IM_MESSAGE_SEND,
            IntentType.CALENDAR_RESCHEDULE: CapabilityId.CALENDAR_RESCHEDULE,
            IntentType.DOC_CREATE: CapabilityId.DOC_CREATE,
            IntentType.SHEET_UPDATE: CapabilityId.SHEET_UPDATE,
            IntentType.UNKNOWN: CapabilityId.UNKNOWN,
        }
        return mapping.get(intent, CapabilityId.UNKNOWN)

    @staticmethod
    def _apply_confirmed_entity(
        parsed: IntentDecision,
        structured_payload: dict[str, object],
        confirmed_entity_id: str,
    ) -> tuple[IntentDecision, dict[str, object]]:
        if not confirmed_entity_id or parsed.intent_type != IntentType.MESSAGE_SEND:
            return parsed, structured_payload
        next_payload = dict(structured_payload)
        candidates = next_payload.get("resolution_candidates", [])
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if str(item.get("entity_id", "")).strip() != confirmed_entity_id:
                    continue
                if str(item.get("entity_type", "")).strip() == "chat":
                    next_payload["chat_id"] = confirmed_entity_id
                    next_payload["user_id"] = ""
                else:
                    next_payload["user_id"] = confirmed_entity_id
                    next_payload["chat_id"] = ""
                next_payload["resolved_name"] = str(item.get("name", "")).strip()
                next_payload["resolution_status"] = "resolved"
                next_payload["resolution_method"] = "user_confirmation"
                next_action = parsed.standard_action.model_copy(update={"payload": next_payload})
                next_structured = {"intent_type": parsed.intent_type.value, "payload": next_payload}
                return parsed.model_copy(
                    update={
                        "standard_action": next_action,
                        "structured_command": next_structured,
                    }
                ), next_payload
        return parsed, next_payload

    @staticmethod
    def _needs_confirmation(parsed: IntentDecision, payload: dict[str, object]) -> bool:
        return (
            parsed.intent_type == IntentType.MESSAGE_SEND
            and str(payload.get("resolution_status", "")).strip() == "needs_confirmation"
        )

    @staticmethod
    def _can_execute_cli(parsed: IntentDecision) -> bool:
        return parsed.selected_executor == ExecutorType.CLI and parsed.intent_type != IntentType.UNKNOWN

    @staticmethod
    def _is_cli_command_implemented(action: StandardAction) -> bool:
        return action.capability_id == CapabilityId.IM_MESSAGE_SEND

    @staticmethod
    def _should_trigger_cua(cli_error_code: str) -> bool:
        triggerable_codes = {
            LarkCliErrorCode.RATE_LIMIT.value,
            LarkCliErrorCode.API_UNSUPPORTED.value,
            LarkCliErrorCode.PERMISSION_DENIED.value,
            LarkCliErrorCode.API_ERROR.value,
            LarkCliErrorCode.RESULT_INVALID.value,
            LarkCliErrorCode.USER_REQUESTED.value,
            LarkCliErrorCode.HYBRID_TASK_REQUIRED.value,
        }
        return bool(cli_error_code and cli_error_code in triggerable_codes)

    @staticmethod
    def _record_step(
        task: OrchestrationTask,
        name: str,
        status: ExecutionStatus,
        summary: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        task.steps.append(
            TaskStep(
                name=name,
                status=status,
                summary=summary,
                payload=payload or {},
            )
        )
