"""Domain enums and state-transition rules."""

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """Lifecycle states for one execution task."""

    QUEUED = "queued"
    PARSING = "parsing"
    CLI_RUNNING = "cli_running"
    CLI_FAILED = "cli_failed"
    CUA_RUNNING = "cua_running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ExecutorType(StrEnum):
    """Executor selection result."""

    CLI = "cli"
    CUA = "cua"
    NONE = "none"


class IntentType(StrEnum):
    """MVP intent categories frozen for challenge sprint."""

    MESSAGE_SEND = "message_send"
    CALENDAR_RESCHEDULE = "calendar_reschedule"
    DOC_CREATE = "doc_create"
    SHEET_UPDATE = "sheet_update"
    UNKNOWN = "unknown"


ALLOWED_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.QUEUED: {ExecutionStatus.PARSING, ExecutionStatus.CANCELED},
    ExecutionStatus.PARSING: {
        ExecutionStatus.CLI_RUNNING,
        ExecutionStatus.CUA_RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    },
    ExecutionStatus.CLI_RUNNING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.CLI_FAILED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    },
    ExecutionStatus.CLI_FAILED: {
        ExecutionStatus.CUA_RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    },
    ExecutionStatus.CUA_RUNNING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELED: set(),
}
