"""Task orchestration from intent parsing through CLI execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
import logging
from typing import Any

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult, OrchestrationTask, PlannedActionItem, StandardAction, TaskStep
from app.schemas.chat import ExecuteCommandRequest, ExecuteCommandResponse
from app.services.cli_failure_diagnosis_service import CliFailureDiagnosis, CliFailureDiagnosisService
from app.services.cua_service import CuaService
from app.services.intent_service import IntentDecision, IntentService
from app.services.lark_cli_service import LarkCliService
from app.services.retry_service import RetryService
from shared.error_codes import UnifiedErrorCode, cli_error_name, normalize_error_code


logger = logging.getLogger(__name__)


class OrchestratorService:
    """Day-6 in-memory orchestrator for task creation and CLI execution."""

    def __init__(
        self,
        intent_service: IntentService | None = None,
        cli_service: LarkCliService | None = None,
        cua_service: CuaService | None = None,
        retry_service: RetryService | None = None,
        diagnosis_service: CliFailureDiagnosisService | None = None,
    ) -> None:
        self.intent_service = intent_service or IntentService()
        self.cli_service = cli_service or LarkCliService()
        self.cua_service = cua_service or CuaService()
        self.retry_service = retry_service or RetryService()
        self.diagnosis_service = diagnosis_service or CliFailureDiagnosisService(intent_service=self.intent_service)
        self._tasks: dict[str, OrchestrationTask] = {}
        self._canceled_task_ids: set[str] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()

    def submit_command(self, payload: ExecuteCommandRequest) -> ExecuteCommandResponse:
        """Create a task immediately and execute it in the background for SSE subscribers."""
        task = OrchestrationTask(
            session_id=payload.session_id,
            user_id=payload.user_id,
            raw_message=payload.message,
        )
        self._tasks[task.task_id] = task
        self._record_step(task, "task_created", ExecutionStatus.QUEUED, "task accepted")
        handle = asyncio.create_task(self._execute_command_background(payload=payload, task=task))
        self._background_tasks.add(handle)
        handle.add_done_callback(self._handle_background_task_done)
        return self._response_from_task(
            task=task,
            selected_executor=ExecutorType.NONE,
            parsed_intent=IntentType.UNKNOWN,
            intent_reason="任务已受理，正在后台执行。",
            action_plan=[],
            parse_source="pending",
            structured_payload={},
            needs_confirmation=False,
            confirmation_message="",
            resolution_candidates=[],
            execution_status=ExecutionStatus.QUEUED,
            execution_summary="任务已受理，状态将通过长连接持续更新。",
            cli_error_code=None,
            cua_error_code=None,
            handoff_error_code=None,
            cua_should_trigger=False,
            execution_payload={},
        )

    async def execute_command(
        self,
        payload: ExecuteCommandRequest,
        task: OrchestrationTask | None = None,
    ) -> ExecuteCommandResponse:
        """Create a task, parse it, optionally execute CLI, and return API ack."""
        if task is None:
            task = OrchestrationTask(
                session_id=payload.session_id,
                user_id=payload.user_id,
                raw_message=payload.message,
            )
            self._tasks[task.task_id] = task
            self._record_step(task, "task_created", ExecutionStatus.QUEUED, "task accepted")

        parsed = await self.intent_service.parse(message=payload.message, context_hint=payload.context_hint)
        structured_payload = self._extract_payload(parsed)

        action = self._standard_action_for(parsed=parsed, payload=structured_payload)
        planned_actions = self._build_planned_action_items(
            parsed=parsed,
            fallback_action=action,
            fallback_payload=structured_payload,
        )
        response_action = planned_actions[0].standard_action if planned_actions else action
        response_payload = self._response_payload_for_items(planned_actions=planned_actions, fallback_payload=structured_payload)
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

        needs_confirmation = False
        task.needs_confirmation = False
        confirmation_message = ""
        execution_status = ExecutionStatus.QUEUED
        execution_summary = "任务已受理，等待后续执行。"
        cli_error_code: int | None = None
        cua_error_code: int | None = None
        cua_should_trigger = False
        any_cua_triggered = False
        execution_payload: dict[str, object] = {}
        resolution_candidates: list[dict[str, object]] = []
        completed_count = 0
        plan_only_count = 0
        failed_count = 0
        handoff_error_code: int | None = None

        if parsed.intent_type == IntentType.UNKNOWN:
            task.status = ExecutionStatus.FAILED
            execution_status = ExecutionStatus.FAILED
            execution_summary = "未找到可执行的标准动作。"
        else:
            for item in task.planned_actions:
                if self._is_cancel_requested(task.task_id):
                    task.status = ExecutionStatus.CANCELED
                    item.status = "canceled"
                    execution_status = ExecutionStatus.CANCELED
                    execution_summary = "task canceled before execution"
                    self._record_step(task, f"action_{item.order}_canceled", ExecutionStatus.CANCELED, execution_summary)
                    break
                item_action = self._prepare_action_for_execution(task=task, item=item)
                item.standard_action = item_action
                if self._action_needs_confirmation(item_action):
                    needs_confirmation = True
                    task.needs_confirmation = True
                    task.status = ExecutionStatus.QUEUED
                    item.status = "needs_confirmation"
                    item.needs_confirmation = True
                    confirmation_message = self._confirmation_message(item_action)
                    item.summary = confirmation_message
                    item.execution_payload = {
                        "mode": "needs_confirmation",
                        "capability_id": item_action.capability_id.value,
                        "payload": dict(item_action.payload),
                    }
                    resolution_candidates = self._resolution_candidates(item_action)
                    execution_status = ExecutionStatus.QUEUED
                    execution_summary = confirmation_message
                    execution_payload = item.execution_payload
                    self._record_step(
                        task,
                        "needs_confirmation" if len(task.planned_actions) == 1 else f"action_{item.order}_needs_confirmation",
                        ExecutionStatus.QUEUED,
                        confirmation_message,
                        {
                            "order": item.order,
                            "resolution_candidates": resolution_candidates,
                        },
                    )
                    break
                if self._is_cli_command_implemented(item_action):
                    item_action = self._ensure_cli_ready_action(item_action)
                    item.standard_action = item_action
                    handoff_error_code = self._action_handoff_error_code(item_action)
                    if handoff_error_code is not None:
                        handoff_payload = self._build_handoff_payload(
                            action=item_action,
                            error_code=handoff_error_code,
                        )
                        handoff_result = ExecutorResult(
                            executor=ExecutorType.CLI,
                            success=False,
                            status=ExecutionStatus.CLI_FAILED,
                            summary=item_action.handoff_reason or "structured handoff requested",
                            payload=handoff_payload,
                            error_code=handoff_error_code,
                        )
                        diagnosis = await self.diagnosis_service.diagnose(
                            action=item_action,
                            result=handoff_result,
                            raw_message=item.raw_message or payload.message,
                        )
                        cua_should_trigger = (
                            self._should_trigger_cua(
                                handoff_error_code,
                                execution_payload=handoff_payload,
                                success=False,
                            )
                            and diagnosis.should_fallback_to_cua
                        )
                        handoff_payload = self._payload_with_cli_diagnosis(
                            payload=handoff_payload,
                            diagnosis=diagnosis,
                            should_fallback_to_cua=cua_should_trigger,
                        )
                        self._record_diagnosis_step(
                            task=task,
                            item=item,
                            diagnosis=diagnosis,
                            should_fallback_to_cua=cua_should_trigger,
                            structured=True,
                        )
                        any_cua_triggered = any_cua_triggered or cua_should_trigger
                        if not cua_should_trigger:
                            task.status = ExecutionStatus.FAILED
                            item.status = "failed"
                            item.summary = diagnosis.user_message
                            item.error_code = handoff_error_code
                            item.execution_payload = handoff_payload
                            task.executor_result = ExecutorResult(
                                executor=ExecutorType.CLI,
                                success=False,
                                status=ExecutionStatus.FAILED,
                                summary=diagnosis.user_message,
                                payload=handoff_payload,
                                error_code=handoff_error_code,
                            )
                            execution_status = ExecutionStatus.FAILED
                            execution_summary = diagnosis.user_message
                            execution_payload = handoff_payload
                            cli_error_code = handoff_error_code
                            failed_count += 1
                            break
                        else:
                            if self._is_cancel_requested(task.task_id):
                                task.status = ExecutionStatus.CANCELED
                                item.status = "canceled"
                                execution_status = ExecutionStatus.CANCELED
                                execution_summary = "task canceled before cua fallback"
                                self._record_step(
                                    task,
                                    f"action_{item.order}_canceled",
                                    ExecutionStatus.CANCELED,
                                    execution_summary,
                                )
                                break
                            cua_result = await asyncio.to_thread(
                                self._execute_cua_fallback,
                                task=task,
                                item=item,
                                action=item_action,
                                raw_message=item.raw_message or payload.message,
                                error_code=handoff_error_code,
                                cli_payload=handoff_payload,
                                trigger_source="structured",
                                diagnosis=diagnosis,
                            )
                            task.executor_result = cua_result
                            execution_status = cua_result.status
                            execution_summary = cua_result.summary
                            execution_payload = cua_result.payload
                            cua_error_code = cua_result.error_code
                            if cua_result.success:
                                any_cua_triggered = True
                                completed_count += 1
                                continue
                            failed_count += 1
                            break

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
                    result = await asyncio.to_thread(
                        self.retry_service.run,
                        lambda: self.cli_service.execute_action(action=item_action, dry_run=False),
                        is_success=lambda item_result: item_result.success,
                        error_code=lambda item_result: item_result.error_code,
                    )
                    cli_error_code = result.error_code
                    diagnosis: CliFailureDiagnosis | None = None
                    cua_should_trigger = False
                    execution_payload = result.payload
                    if result.success:
                        cua_should_trigger = False
                    else:
                        diagnosis = await self.diagnosis_service.diagnose(
                            action=item_action,
                            result=result,
                            raw_message=item.raw_message or payload.message,
                        )
                        cua_should_trigger = (
                            self._should_trigger_cua(
                                cli_error_code,
                                execution_payload=result.payload,
                                success=result.success,
                            )
                            and diagnosis.should_fallback_to_cua
                        )
                        execution_payload = self._payload_with_cli_diagnosis(
                            payload=result.payload,
                            diagnosis=diagnosis,
                            should_fallback_to_cua=cua_should_trigger,
                        )
                        summary = result.summary if cua_should_trigger else diagnosis.user_message
                        status = result.status if cua_should_trigger else ExecutionStatus.FAILED
                        result = result.model_copy(
                            update={
                                "status": status,
                                "summary": summary,
                                "payload": execution_payload,
                            }
                        )
                    task.executor_result = result
                    item.summary = result.summary
                    item.error_code = result.error_code
                    item.execution_payload = execution_payload
                    execution_status = result.status
                    execution_summary = result.summary
                    any_cua_triggered = any_cua_triggered or cua_should_trigger
                    task.status = result.status
                    item.status = "completed" if result.success else "cli_failed" if cua_should_trigger else "failed"
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
                            "diagnosis": diagnosis.model_dump() if diagnosis is not None else {},
                        },
                    )
                    if diagnosis is not None:
                        self._record_diagnosis_step(
                            task=task,
                            item=item,
                            diagnosis=diagnosis,
                            should_fallback_to_cua=cua_should_trigger,
                            structured=False,
                        )
                    if self._is_cancel_requested(task.task_id):
                        task.status = ExecutionStatus.CANCELED
                        item.status = "canceled"
                        execution_status = ExecutionStatus.CANCELED
                        execution_summary = "task canceled after cli execution"
                        self._record_step(
                            task,
                            f"action_{item.order}_canceled",
                            ExecutionStatus.CANCELED,
                            execution_summary,
                        )
                        break
                    if cua_should_trigger:
                        if self._is_cancel_requested(task.task_id):
                            task.status = ExecutionStatus.CANCELED
                            item.status = "canceled"
                            execution_status = ExecutionStatus.CANCELED
                            execution_summary = "task canceled before cua fallback"
                            self._record_step(
                                task,
                                f"action_{item.order}_canceled",
                                ExecutionStatus.CANCELED,
                                execution_summary,
                            )
                            break
                        cua_result = await asyncio.to_thread(
                            self._execute_cua_fallback,
                            task=task,
                            item=item,
                            action=item_action,
                            raw_message=item.raw_message or payload.message,
                            error_code=cli_error_code,
                            cli_payload=execution_payload,
                            trigger_source="cli",
                            diagnosis=diagnosis,
                        )
                        task.executor_result = cua_result
                        execution_status = cua_result.status
                        execution_summary = cua_result.summary
                        execution_payload = cua_result.payload
                        cua_error_code = cua_result.error_code
                        if cua_result.success:
                            any_cua_triggered = True
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
                task.status = ExecutionStatus.QUEUED
                execution_status = ExecutionStatus.QUEUED
                execution_summary = item.summary
                execution_payload = item.execution_payload
                plan_only_count += 1
                self._record_step(
                    task,
                    f"action_{item.order}_planned_only",
                    ExecutionStatus.QUEUED,
                    item.summary,
                    {"order": item.order, "capability_id": item_action.capability_id.value},
                )

        if len(task.planned_actions) > 1:
            aggregate_duration_ms = round(
                sum(self._execution_payload_duration_ms(item.execution_payload) for item in task.planned_actions),
                2,
            )
            aggregate_executor = (
                ExecutorType.CUA
                if any(
                    isinstance(item.execution_payload, dict) and item.execution_payload.get("mode") == "cua_fallback"
                    for item in task.planned_actions
                )
                else ExecutorType.CLI
            )
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
            elif task.status == ExecutionStatus.CANCELED:
                execution_status = ExecutionStatus.CANCELED
                execution_summary = f"planned {len(task.planned_actions)} tasks; {completed_count} completed, {plan_only_count} structured-only, canceled"
            else:
                execution_status = ExecutionStatus.COMPLETED
                task.status = ExecutionStatus.COMPLETED
                execution_summary = f"planned {len(task.planned_actions)} tasks; {completed_count} completed, {plan_only_count} structured-only"
            task.executor_result = ExecutorResult(
                executor=aggregate_executor,
                success=execution_status == ExecutionStatus.COMPLETED,
                status=execution_status,
                summary=execution_summary,
                payload=execution_payload,
                error_code=cua_error_code or cli_error_code,
                duration_ms=aggregate_duration_ms,
            )

        task.updated_at = datetime.now(UTC)
        self._tasks[task.task_id] = task
        response_action = task.planned_actions[0].standard_action if task.planned_actions else response_action
        task.standard_action = response_action
        response_payload = self._response_payload_for_items(
            planned_actions=task.planned_actions,
            fallback_payload=response_payload,
        )

        return self._response_from_task(
            task=task,
            selected_executor=parsed.selected_executor,
            parsed_intent=parsed.intent_type,
            intent_reason=parsed.reason,
            action_plan=parsed.action_plan,
            parse_source=parsed.parse_source,
            structured_payload=response_payload,
            needs_confirmation=needs_confirmation,
            confirmation_message=confirmation_message,
            resolution_candidates=resolution_candidates,
            execution_status=execution_status,
            execution_summary=execution_summary,
            cli_error_code=cli_error_code,
            cua_error_code=cua_error_code,
            handoff_error_code=handoff_error_code,
            cua_should_trigger=any_cua_triggered,
            execution_payload=execution_payload,
        )

    def get_task(self, task_id: str) -> OrchestrationTask | None:
        """Return an in-memory task record by ID."""
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> OrchestrationTask | None:
        """Mark a non-terminal in-memory task as canceled for sidebar controls."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELED,
        }:
            return task
        self._canceled_task_ids.add(task_id)
        task.status = ExecutionStatus.CANCELED
        task.updated_at = datetime.now(UTC)
        self._record_step(
            task,
            "user_canceled",
            ExecutionStatus.CANCELED,
            "用户在前端请求取消任务。",
        )
        return task

    @staticmethod
    def _response_from_task(
        *,
        task: OrchestrationTask,
        selected_executor: ExecutorType,
        parsed_intent: IntentType,
        intent_reason: str,
        action_plan: list[str],
        parse_source: str,
        structured_payload: dict[str, object],
        needs_confirmation: bool,
        confirmation_message: str,
        resolution_candidates: list[dict[str, object]],
        execution_status: ExecutionStatus,
        execution_summary: str,
        cli_error_code: int | None,
        cua_error_code: int | None,
        handoff_error_code: int | None,
        cua_should_trigger: bool,
        execution_payload: dict[str, object],
    ) -> ExecuteCommandResponse:
        return ExecuteCommandResponse(
            task_id=task.task_id,
            initial_status=ExecutionStatus.QUEUED,
            selected_executor=selected_executor,
            parsed_intent=parsed_intent,
            intent_reason=intent_reason,
            action_plan=action_plan,
            parse_source=parse_source,
            standard_action=task.standard_action,
            planned_actions=task.planned_actions,
            structured_payload=structured_payload,
            needs_confirmation=needs_confirmation,
            confirmation_message=confirmation_message,
            resolution_candidates=resolution_candidates,
            execution_status=execution_status,
            execution_summary=execution_summary,
            cli_error_code=cli_error_code,
            cua_error_code=cua_error_code,
            handoff_error_code=handoff_error_code,
            cua_should_trigger=cua_should_trigger,
            execution_payload=execution_payload,
            accepted_at=task.created_at,
        )

    async def _execute_command_background(self, *, payload: ExecuteCommandRequest, task: OrchestrationTask) -> None:
        try:
            await self.execute_command(payload, task=task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("background orchestration task failed")
            task.status = ExecutionStatus.FAILED
            task.updated_at = datetime.now(UTC)
            error_message = f"后台执行失败：{exc}"
            self._record_step(
                task,
                "background_failed",
                ExecutionStatus.FAILED,
                error_message,
                {"error": str(exc)},
            )
            task.executor_result = ExecutorResult(
                executor=ExecutorType.NONE,
                success=False,
                status=ExecutionStatus.FAILED,
                summary=error_message,
                payload={"error": {"message": error_message}},
                error_code=int(UnifiedErrorCode.EXECUTION_ERROR),
            )
            self._tasks[task.task_id] = task

    def _handle_background_task_done(self, handle: asyncio.Task[None]) -> None:
        self._background_tasks.discard(handle)
        try:
            handle.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("background orchestration task failed")

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
                    needs_confirmation=False,
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
    def _response_payload_for_items(
        planned_actions: list[PlannedActionItem],
        fallback_payload: dict[str, object],
    ) -> dict[str, object]:
        if planned_actions:
            return dict(planned_actions[0].standard_action.payload)
        return dict(fallback_payload)

    @staticmethod
    def _is_cli_command_implemented(action: StandardAction) -> bool:
        return action.capability_id in {
            CapabilityId.IM_MESSAGE_SEND,
            CapabilityId.IM_MESSAGES_REPLY,
            CapabilityId.IM_MESSAGES_SEARCH,
            CapabilityId.IM_CHAT_MESSAGES_LIST,
            CapabilityId.IM_CHAT_SEARCH,
            CapabilityId.IM_CHAT_CREATE,
            CapabilityId.CALENDAR_CREATE,
            CapabilityId.CALENDAR_AGENDA,
            CapabilityId.CALENDAR_FREEBUSY,
            CapabilityId.DOC_CREATE,
            CapabilityId.DOC_UPDATE,
            CapabilityId.DOC_SEARCH,
        }

    def _is_cancel_requested(self, task_id: str) -> bool:
        return task_id in self._canceled_task_ids

    @staticmethod
    def _should_trigger_cua(
        cli_error_code: int | None,
        execution_payload: dict[str, object] | None = None,
        success: bool = False,
    ) -> bool:
        if success:
            return False
        if cli_error_code is not None:
            normalized_code = normalize_error_code(cli_error_code)
            return normalized_code is not None and int(normalized_code) != 0
        return True

    @staticmethod
    def _action_needs_confirmation(action: StandardAction) -> bool:
        return str(action.payload.get("resolution_status", "")).strip() == "needs_confirmation"

    @staticmethod
    def _confirmation_message(action: StandardAction) -> str:
        hint = str(action.payload.get("chat_hint", "")).strip()
        if hint:
            return f"需要确认发送对象：{hint}"
        return "需要确认发送对象后再执行。"

    @staticmethod
    def _resolution_candidates(action: StandardAction) -> list[dict[str, object]]:
        raw_candidates = action.payload.get("resolution_candidates")
        if not isinstance(raw_candidates, list):
            return []
        candidates: list[dict[str, object]] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "name": str(item.get("name", "")).strip(),
                    "entity_type": str(item.get("entity_type", "")).strip(),
                    "entity_id": str(item.get("entity_id", "")).strip(),
                    "score": float(item.get("score", 0) or 0),
                }
            )
        return [item for item in candidates if item["name"] and item["entity_id"]]

    def _execute_cua_fallback(
        self,
        *,
        task: OrchestrationTask,
        item: PlannedActionItem,
        action: StandardAction,
        raw_message: str,
        error_code: int | None,
        cli_payload: dict[str, object],
        trigger_source: str = "cli",
        diagnosis: CliFailureDiagnosis | None = None,
    ) -> ExecutorResult:
        task.status = ExecutionStatus.CUA_RUNNING
        item.status = "cua_running"
        task.updated_at = datetime.now(UTC)
        cua_started_name = "cua_started" if len(task.planned_actions) == 1 else f"action_{item.order}_cua_started"
        diagnosis_payload = diagnosis.model_dump() if diagnosis is not None else {}
        summary = (
            diagnosis.user_message
            if diagnosis is not None
            else "standard error code produced, switching to cua fallback"
        )
        self._record_step(
            task,
            cua_started_name,
            ExecutionStatus.CUA_RUNNING,
            summary,
            {
                "order": item.order,
                "error_code": error_code,
                "diagnosis": diagnosis_payload,
                "cua_handoff_message": summary,
            },
        )
        cua_result = self.cua_service.execute_fallback(
            action=action,
            raw_message=raw_message,
            task_id=task.task_id,
            session_id=task.session_id,
            chain_id=task.task_id,
            cli_error_code=error_code,
            cli_payload=cli_payload,
            retry_attempts=max(1, int(self.retry_service.policy.max_attempts)),
            trigger_source=trigger_source,
        )
        if diagnosis is not None:
            cua_result = cua_result.model_copy(
                update={
                    "payload": self._payload_with_cli_diagnosis(
                        payload=cua_result.payload,
                        diagnosis=diagnosis,
                        should_fallback_to_cua=True,
                    ),
                }
            )
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
        return cua_result

    @staticmethod
    def _payload_with_cli_diagnosis(
        *,
        payload: dict[str, object],
        diagnosis: CliFailureDiagnosis,
        should_fallback_to_cua: bool,
    ) -> dict[str, object]:
        next_payload = dict(payload)
        diagnosis_payload = diagnosis.model_dump()
        diagnosis_payload["should_fallback_to_cua"] = should_fallback_to_cua
        next_payload["cli_failure_diagnosis"] = diagnosis_payload
        next_payload["cua_handoff_message"] = (
            diagnosis.user_message if should_fallback_to_cua else "模型诊断后判定暂不接管 CUA。"
        )
        return next_payload

    def _record_diagnosis_step(
        self,
        *,
        task: OrchestrationTask,
        item: PlannedActionItem,
        diagnosis: CliFailureDiagnosis,
        should_fallback_to_cua: bool,
        structured: bool,
    ) -> None:
        name_suffix = "structured_diagnosed" if structured else "cli_diagnosed"
        step_name = name_suffix if len(task.planned_actions) == 1 else f"action_{item.order}_{name_suffix}"
        self._record_step(
            task,
            step_name,
            ExecutionStatus.CLI_FAILED if should_fallback_to_cua else ExecutionStatus.FAILED,
            diagnosis.user_message,
            {
                "order": item.order,
                "should_fallback_to_cua": should_fallback_to_cua,
                "diagnosis": diagnosis.model_dump(),
            },
        )

    @staticmethod
    def _action_handoff_error_code(action: StandardAction) -> int | None:
        code = normalize_error_code(action.handoff_error_code)
        if code is None:
            code = normalize_error_code(action.payload.get("handoff_error_code"))
        return int(code) if code is not None and int(code) != 0 else None

    @staticmethod
    def _build_handoff_payload(action: StandardAction, error_code: int) -> dict[str, object]:
        handoff_reason = str(action.handoff_reason or action.payload.get("handoff_reason", "")).strip()
        return {
            "mode": "structured_handoff",
            "capability_id": action.capability_id.value,
            "payload": dict(action.payload),
            "error": {
                "code": error_code,
                "name": cli_error_name(error_code),
                "message": handoff_reason or "structured handoff requested",
            },
        }

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
    def _ensure_cli_ready_action(action: StandardAction) -> StandardAction:
        if action.capability_id != CapabilityId.IM_MESSAGE_SEND:
            return action
        payload = dict(action.payload)
        chat_id = str(payload.get("chat_id", "")).strip()
        user_id = str(payload.get("user_id", "")).strip()
        if chat_id or user_id:
            return action
        hint = str(payload.get("chat_hint", "")).strip()
        if hint:
            payload["resolution_status"] = "handoff_required"
            payload["resolution_reason"] = "message_target_unresolved"
            payload["handoff_error_code"] = int(UnifiedErrorCode.HANDOFF_REQUIRED)
            payload.setdefault("handoff_reason", "recipient target is unresolved before CLI execution")
            handoff_code = OrchestratorService._action_handoff_error_code(action.model_copy(update={"payload": payload}))
            return action.model_copy(
                update={
                    "payload": payload,
                    "handoff_error_code": handoff_code,
                    "handoff_reason": str(payload.get("handoff_reason", "")).strip(),
                }
            )
        payload["handoff_error_code"] = int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
        payload["resolution_status"] = "missing_required_field"
        payload["resolution_reason"] = "missing_message_target"
        payload.setdefault("handoff_reason", "message recipient is missing")
        return action.model_copy(
            update={
                "payload": payload,
                "handoff_error_code": OrchestratorService._action_handoff_error_code(action.model_copy(update={"payload": payload})),
                "handoff_reason": str(payload.get("handoff_reason", "")).strip(),
            }
        )

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

    @staticmethod
    def _execution_payload_duration_ms(payload: dict[str, object]) -> float:
        if not isinstance(payload, dict):
            return 0.0
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            return 0.0
        return sum(
            float(step.get("duration_ms", 0) or 0)
            for step in raw_steps
            if isinstance(step, dict)
        )
