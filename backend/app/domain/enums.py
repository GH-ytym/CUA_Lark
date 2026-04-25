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


class LarkCliErrorCode(StrEnum):
    """CLI failure codes aligned to cua.trigger_rules.LarkCliError."""

    RATE_LIMIT = "rate_limit_exceeded"
    API_UNSUPPORTED = "api_unsupported"
    PERMISSION_DENIED = "permission_denied"
    API_ERROR = "api_internal_error"
    RESULT_INVALID = "result_invalid"
    USER_REQUESTED = "user_requested"
    HYBRID_TASK_REQUIRED = "hybrid_task_required"


class CuaAbortReason(StrEnum):
    """Abort reasons aligned to cua.trigger_rules.CuaAbortReason."""

    LOW_CONFIDENCE = "low_confidence"
    TIMEOUT = "operation_timeout"
    INTERFACE_CHANGED = "interface_unexpectedly_changed"
    MAX_RETRY_EXCEEDED = "max_retry_exceeded"
    SECURITY_RISK = "security_risk_detected"
    USER_INTERRUPTED = "user_interrupted"
    MULTI_MONITOR_UNSUPPORTED = "multi_monitor_unsupported"


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
