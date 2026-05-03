"""Task orchestration from intent parsing through CLI execution."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import OrchestrationTask, PlannedActionItem, StandardAction, TaskStep
from app.schemas.chat import ExecuteCommandRequest, ExecuteCommandResponse
from app.services.cua_service import CuaService
from app.services.intent_service import IntentDecision, IntentService
from app.services.lark_cli_service import LarkCliService
from shared.error_codes import CLI_TRIGGER_ERROR_CODES, cli_error_name, normalize_error_code


class OrchestratorService:
    """Day-6 in-memory orchestrator for task creation and CLI execution."""

    def __init__(
        self,
        intent_service: IntentService | None = None,
        cli_service: LarkCliService | None = None,
        cua_service: CuaService | None = None,
    ) -> None:
        self.intent_service = intent_service or IntentService()
        self.cli_service = cli_service or LarkCliService()
        self.cua_service = cua_service or CuaService()
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
        planned_actions = self._build_planned_action_items(
            parsed=parsed,
            fallback_action=action,
            fallback_payload=structured_payload,
        )
        response_action = planned_actions[0].standard_action if planned_actions else action
        response_payload = self._response_payload_for_items(planned_actions=planned_actions, fallback_payload=structured_payload)
        confirmation_order = self._first_confirmation_order(planned_actions=planned_actions)
        task.intent_type = parsed.intent_type
        task.standard_action = response_action
        task.planned_actions = planned_actions
        task.status = ExecutionStatus.PARSING
        task.updated_at = datetime.now(UTC)
        self._record_step(
            task,
            "intent_parsed",
            ExecutionStatus.PARSING,
            parsed.reason,
            {
                "capability_id": action.capability_id.value,
                "parse_source": parsed.parse_source,
                "planned_action_count": len(planned_actions),
            },
        )

        needs_confirmation = any(item.needs_confirmation for item in planned_actions)
        task.needs_confirmation = needs_confirmation
        confirmation_message = "请先确认要发送给谁，再继续执行。" if needs_confirmation else ""
        execution_status = ExecutionStatus.QUEUED
        execution_summary = "任务已受理，等待后续执行。"
        cli_error_code: int | None = None
        cua_error_code: int | None = None
        cua_should_trigger = False
        execution_payload: dict[str, object] = {}
        completed_count = 0
        plan_only_count = 0
        failed_count = 0

        if needs_confirmation:
            confirmation_step_name = (
                "confirmation_required"
                if len(task.planned_actions) == 1
                else f"action_{confirmation_order}_confirmation_required"
            )
            self._record_step(task, confirmation_step_name, ExecutionStatus.QUEUED, confirmation_message)
        elif parsed.intent_type == IntentType.UNKNOWN:
            task.status = ExecutionStatus.FAILED
            execution_status = ExecutionStatus.FAILED
            execution_summary = "未找到可执行的标准动作。"
        else:
            for item in task.planned_actions:
                item_action = self._prepare_action_for_execution(task=task, item=item)
                item.standard_action = item_action
                if self._is_cli_command_implemented(item_action):
                    task.status = ExecutionStatus.CLI_RUNNING
                    item.status = "cli_running"
                    cli_started_name = "cli_started" if len(task.planned_actions) == 1 else f"action_{item.order}_cli_started"
                    self._record_step(
                        task,
                        cli_started_name,
                        ExecutionStatus.CLI_RUNNING,
                        item_action.capability_id.value,
                        {"order": item.order, "raw_message": item.raw_message},
                    )
                    result = self.cli_service.execute_action(action=item_action, dry_run=False)
                    task.executor_result = result
                    item.summary = result.summary
                    item.error_code = result.error_code
                    item.execution_payload = result.payload
                    execution_status = result.status
                    execution_summary = result.summary
                    execution_payload = result.payload
                    cli_error_code = result.error_code
                    cua_should_trigger = self._should_trigger_cua(
                        cli_error_code,
                        execution_payload=execution_payload,
                        success=result.success,
                    )
                    task.status = result.status
                    item.status = "completed" if result.success else "cli_failed"
                    cli_finished_name = "cli_finished" if len(task.planned_actions) == 1 else f"action_{item.order}_cli_finished"
                    self._record_step(
                        task,
                        cli_finished_name,
                        result.status,
                        result.summary,
                        {
                            "order": item.order,
                            "error_code": cli_error_code,
                            "cua_should_trigger": cua_should_trigger,
                        },
                    )
                    if cua_should_trigger:
                        task.status = ExecutionStatus.CUA_RUNNING
                        item.status = "cua_running"
                        task.updated_at = datetime.now(UTC)
                        cua_started_name = "cua_started" if len(task.planned_actions) == 1 else f"action_{item.order}_cua_started"
                        self._record_step(
                            task,
                            cua_started_name,
                            ExecutionStatus.CUA_RUNNING,
                            "cli failed, switching to cua fallback",
                            {"order": item.order, "cli_error_code": cli_error_code},
                        )
                        cua_result = self.cua_service.execute_fallback(
                            action=item_action,
                            raw_message=item.raw_message or payload.message,
                            task_id=task.task_id,
                            cli_error_code=cli_error_code,
                            cli_payload=execution_payload,
                        )
                        task.executor_result = cua_result
                        execution_status = cua_result.status
                        execution_summary = cua_result.summary
                        execution_payload = cua_result.payload
                        cua_error_code = cua_result.error_code
                        item.summary = cua_result.summary
                        item.error_code = cua_result.error_code
                        item.execution_payload = cua_result.payload
                        item.status = "completed" if cua_result.success else "failed"
                        task.status = cua_result.status
                        task.updated_at = datetime.now(UTC)
                        cua_finished_name = "cua_finished" if len(task.planned_actions) == 1 else f"action_{item.order}_cua_finished"
                        self._record_step(
                            task,
                            cua_finished_name,
                            cua_result.status,
                            cua_result.summary,
                            cua_result.payload,
                        )
                        if cua_result.success:
                            completed_count += 1
                            continue
                        failed_count += 1
                        break
                    if result.success:
                        completed_count += 1
                        continue
                    failed_count += 1
                    break

                item.status = "plan_only"
                item.summary = (
                    "structured output ready; sequential execution is deferred for "
                    f"{item_action.capability_id.value}"
                )
                item.execution_payload = {
                    "mode": "structured_only",
                    "capability_id": item_action.capability_id.value,
                    "payload": dict(item_action.payload),
                }
                plan_only_count += 1
                self._record_step(
                    task,
                    f"action_{item.order}_planned_only",
                    ExecutionStatus.QUEUED,
                    item.summary,
                    {"order": item.order, "capability_id": item_action.capability_id.value},
                )

        if len(task.planned_actions) > 1:
            execution_payload = {
                "mode": "multi_task",
                "actions": [item.model_dump() for item in task.planned_actions],
                "completed_count": completed_count,
                "plan_only_count": plan_only_count,
                "failed_count": failed_count,
            }
            if failed_count > 0:
                execution_status = ExecutionStatus.FAILED
                task.status = ExecutionStatus.FAILED
                execution_summary = f"planned {len(task.planned_actions)} tasks; {completed_count} completed, {plan_only_count} structured-only, {failed_count} failed"
            elif needs_confirmation:
                execution_status = ExecutionStatus.QUEUED
                task.status = ExecutionStatus.QUEUED
                execution_summary = confirmation_message
            else:
                execution_status = ExecutionStatus.COMPLETED
                task.status = ExecutionStatus.COMPLETED
                execution_summary = f"planned {len(task.planned_actions)} tasks; {completed_count} completed, {plan_only_count} structured-only"

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
            standard_action=response_action,
            planned_actions=task.planned_actions,
            structured_payload=response_payload,
            needs_confirmation=needs_confirmation,
            confirmation_message=confirmation_message,
            resolution_candidates=response_payload.get("resolution_candidates", []),
            execution_status=execution_status,
            execution_summary=execution_summary,
            cli_error_code=cli_error_code,
            cua_error_code=cua_error_code,
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
        if isinstance(payload, dict):
            return dict(payload)
        tasks = structured.get("tasks")
        if isinstance(tasks, list) and tasks:
            first = tasks[0]
            if isinstance(first, dict):
                task_payload = first.get("payload")
                if isinstance(task_payload, dict):
                    return dict(task_payload)
        return dict(parsed.standard_action.payload)

    @staticmethod
    def _build_planned_action_items(
        parsed: IntentDecision,
        fallback_action: StandardAction,
        fallback_payload: dict[str, object],
    ) -> list[PlannedActionItem]:
        if parsed.planned_actions:
            actions = parsed.planned_actions
        elif parsed.standard_action.capability_id != CapabilityId.UNKNOWN or parsed.intent_type == IntentType.UNKNOWN:
            actions = [parsed.standard_action]
        else:
            actions = [fallback_action.model_copy(update={"payload": fallback_payload})]
        clauses = parsed.task_clauses or ["" for _ in actions]
        items: list[PlannedActionItem] = []
        for index, action in enumerate(actions, start=1):
            raw_message = clauses[index - 1] if index - 1 < len(clauses) else ""
            payload = dict(action.payload)
            items.append(
                PlannedActionItem(
                    order=index,
                    raw_message=raw_message,
                    standard_action=action,
                    status="planned",
                    summary="structured output ready",
                    needs_confirmation=OrchestratorService._needs_confirmation_for_action(action=action, payload=payload),
                )
            )
        return items

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
        if not confirmed_entity_id:
            return parsed, structured_payload
        if parsed.intent_type == IntentType.MULTI_TASK and parsed.planned_actions:
            return OrchestratorService._apply_confirmed_entity_for_multitask(parsed=parsed, confirmed_entity_id=confirmed_entity_id)
        if parsed.intent_type != IntentType.MESSAGE_SEND:
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
    def _apply_confirmed_entity_for_multitask(
        parsed: IntentDecision,
        confirmed_entity_id: str,
    ) -> tuple[IntentDecision, dict[str, object]]:
        next_actions: list[StandardAction] = []
        matched_payload: dict[str, object] | None = None
        for action in parsed.planned_actions:
            next_action, next_payload = OrchestratorService._apply_confirmed_entity_to_action(
                action=action,
                confirmed_entity_id=confirmed_entity_id,
            )
            if next_payload is not None and matched_payload is None:
                matched_payload = next_payload
            next_actions.append(next_action)

        if matched_payload is None:
            return parsed, dict(parsed.planned_actions[0].payload) if parsed.planned_actions else {}

        next_structured = dict(parsed.structured_command)
        tasks = next_structured.get("tasks")
        if isinstance(tasks, list):
            updated_tasks: list[dict[str, object]] = []
            for index, task in enumerate(tasks):
                if not isinstance(task, dict):
                    continue
                updated_task = dict(task)
                if index < len(next_actions):
                    updated_task["payload"] = dict(next_actions[index].payload)
                    updated_task["capability_id"] = next_actions[index].capability_id.value
                    updated_task["intent_type"] = next_actions[index].intent_type.value
                updated_tasks.append(updated_task)
            next_structured["tasks"] = updated_tasks

        next_standard_action = next_actions[0] if next_actions else parsed.standard_action
        return parsed.model_copy(
            update={
                "standard_action": next_standard_action,
                "planned_actions": next_actions,
                "structured_command": next_structured,
            }
        ), dict(next_standard_action.payload)

    @staticmethod
    def _apply_confirmed_entity_to_action(
        action: StandardAction,
        confirmed_entity_id: str,
    ) -> tuple[StandardAction, dict[str, object] | None]:
        if action.intent_type != IntentType.MESSAGE_SEND:
            return action, None
        next_payload = dict(action.payload)
        candidates = next_payload.get("resolution_candidates", [])
        if not isinstance(candidates, list):
            return action, None
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
            return action.model_copy(update={"payload": next_payload}), next_payload
        return action, None

    @staticmethod
    def _needs_confirmation(parsed: IntentDecision, payload: dict[str, object]) -> bool:
        return (
            parsed.intent_type == IntentType.MESSAGE_SEND
            and str(payload.get("resolution_status", "")).strip() == "needs_confirmation"
        )

    @staticmethod
    def _needs_confirmation_for_action(action: StandardAction, payload: dict[str, object]) -> bool:
        return (
            action.intent_type == IntentType.MESSAGE_SEND
            and str(payload.get("resolution_status", "")).strip() == "needs_confirmation"
        )

    @staticmethod
    def _first_confirmation_order(planned_actions: list[PlannedActionItem]) -> int:
        for item in planned_actions:
            if item.needs_confirmation:
                return item.order
        return 1

    @staticmethod
    def _response_payload_for_items(
        planned_actions: list[PlannedActionItem],
        fallback_payload: dict[str, object],
    ) -> dict[str, object]:
        for item in planned_actions:
            if item.needs_confirmation:
                return dict(item.standard_action.payload)
        if planned_actions:
            return dict(planned_actions[0].standard_action.payload)
        return dict(fallback_payload)

    @staticmethod
    def _can_execute_cli(parsed: IntentDecision) -> bool:
        return parsed.selected_executor == ExecutorType.CLI and parsed.intent_type != IntentType.UNKNOWN

    @staticmethod
    def _is_cli_command_implemented(action: StandardAction) -> bool:
        return action.capability_id in {
            CapabilityId.IM_MESSAGE_SEND,
            CapabilityId.DOC_CREATE,
            CapabilityId.DOC_UPDATE,
            CapabilityId.DOC_SEARCH,
        }

    @staticmethod
    def _should_trigger_cua(
        cli_error_code: int | None,
        execution_payload: dict[str, object] | None = None,
        success: bool = False,
    ) -> bool:
        evaluator_cls = OrchestratorService._load_trigger_rule_evaluator()
        normalized_code = normalize_error_code(cli_error_code)
        cli_result = {
            "success": success,
            "error_code": int(normalized_code) if normalized_code is not None else None,
            "data": OrchestratorService._extract_trigger_data(execution_payload or {}),
        }
        if evaluator_cls is not None:
            return bool(evaluator_cls().should_trigger_cua(cli_result))
        return normalized_code is not None and int(normalized_code) in CLI_TRIGGER_ERROR_CODES

    @staticmethod
    def _extract_trigger_data(execution_payload: dict[str, object]) -> object:
        if execution_payload.get("error") is not None:
            return None
        steps = execution_payload.get("steps")
        if isinstance(steps, list) and steps:
            return steps
        return execution_payload or None

    @staticmethod
    def _load_trigger_rule_evaluator() -> type[Any] | None:
        project_root = Path(__file__).resolve().parents[3]
        project_root_text = str(project_root)
        if project_root_text not in sys.path:
            sys.path.append(project_root_text)
        try:
            from cua.trigger_rules import TriggerRuleEvaluator
        except Exception:  # noqa: BLE001
            return None
        return TriggerRuleEvaluator

    @staticmethod
    def _prepare_action_for_execution(task: OrchestrationTask, item: PlannedActionItem) -> StandardAction:
        action = item.standard_action
        if not OrchestratorService._requires_idempotency_key(action):
            return action
        payload = dict(action.payload)
        if str(payload.get("idempotency_key", "")).strip():
            return action
        payload["idempotency_key"] = OrchestratorService._build_idempotency_key(
            task_id=task.task_id,
            order=item.order,
            capability_id=action.capability_id.value,
            payload=payload,
        )
        return action.model_copy(update={"payload": payload})

    @staticmethod
    def _requires_idempotency_key(action: StandardAction) -> bool:
        return action.capability_id in {CapabilityId.IM_MESSAGE_SEND, CapabilityId.IM_MESSAGES_REPLY}

    @staticmethod
    def _build_idempotency_key(
        task_id: str,
        order: int,
        capability_id: str,
        payload: dict[str, object],
    ) -> str:
        stable_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"idempotency_key", "resolution_candidates", "resolution_method"}
        }
        serialized = json.dumps(
            {
                "task_id": task_id,
                "order": order,
                "capability_id": capability_id,
                "payload": stable_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]
        return f"fsagent-{task_id[:8]}-{order}-{digest}"

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
