"""Translate backend task state into ordered sidebar stream events."""

from datetime import UTC, datetime

from app.domain.enums import ExecutionStatus
from app.domain.models import OrchestrationTask, TaskStep
from app.schemas.execution import ExecutionDetailResponse, ExecutionStreamEvent


TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELED,
}


class ExecutionStreamFormatter:
    """Build stable stream payloads from in-memory orchestration tasks."""

    @staticmethod
    def is_terminal(status: ExecutionStatus) -> bool:
        """Return whether a task status should close the SSE stream."""
        return status in TERMINAL_STATUSES

    @staticmethod
    def detail_from_task(task: OrchestrationTask) -> ExecutionDetailResponse:
        """Convert the domain task into the public execution detail schema."""
        return ExecutionDetailResponse.model_validate(task.model_dump())

    def snapshot_event(self, task: OrchestrationTask, sequence: int) -> ExecutionStreamEvent:
        """Return the first event for a stream subscriber."""
        detail = self.detail_from_task(task)
        return ExecutionStreamEvent(
            event="snapshot",
            task_id=task.task_id,
            status=task.status,
            sequence=sequence,
            summary="execution snapshot",
            detail=detail,
            emitted_at=datetime.now(UTC),
        )

    def step_event(self, task: OrchestrationTask, step: TaskStep, sequence: int) -> ExecutionStreamEvent:
        """Return one recorded orchestration step as a stream event."""
        return ExecutionStreamEvent(
            event="step",
            task_id=task.task_id,
            status=step.status,
            sequence=sequence,
            summary=step.summary,
            step=step,
            emitted_at=datetime.now(UTC),
        )

    def status_event(self, task: OrchestrationTask, sequence: int) -> ExecutionStreamEvent:
        """Return a lightweight state-change event when status changes without a new step."""
        return ExecutionStreamEvent(
            event="status",
            task_id=task.task_id,
            status=task.status,
            sequence=sequence,
            summary=task.executor_result.summary if task.executor_result is not None else task.status.value,
            emitted_at=datetime.now(UTC),
        )

    def heartbeat_event(self, task: OrchestrationTask, sequence: int) -> ExecutionStreamEvent:
        """Return a keepalive event so long-running CUA tasks keep the browser stream open."""
        return ExecutionStreamEvent(
            event="heartbeat",
            task_id=task.task_id,
            status=task.status,
            sequence=sequence,
            summary="keepalive",
            emitted_at=datetime.now(UTC),
        )

    def terminal_event(self, task: OrchestrationTask, sequence: int) -> ExecutionStreamEvent:
        """Return the final event with a fresh detail snapshot."""
        detail = self.detail_from_task(task)
        summary = task.executor_result.summary if task.executor_result is not None else task.status.value
        return ExecutionStreamEvent(
            event="terminal",
            task_id=task.task_id,
            status=task.status,
            sequence=sequence,
            summary=summary,
            detail=detail,
            emitted_at=datetime.now(UTC),
        )
