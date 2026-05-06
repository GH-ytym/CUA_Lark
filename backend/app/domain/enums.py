"""Domain enums and state-transition rules."""

from enum import IntEnum, StrEnum

from shared.error_codes import UnifiedErrorCode


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
    MULTI_TASK = "multi_task"
    UNKNOWN = "unknown"


class CapabilityId(StrEnum):
    """Capability-level action identifiers used by the orchestrator."""

    IM_MESSAGE_SEND = "im.message_send"
    IM_MESSAGES_REPLY = "im.messages_reply"
    IM_MESSAGES_SEARCH = "im.messages_search"
    IM_CHAT_MESSAGES_LIST = "im.chat_messages_list"
    IM_CHAT_SEARCH = "im.chat_search"
    IM_CHAT_CREATE = "im.chat_create"
    CALENDAR_RESCHEDULE = "calendar.reschedule"
    CALENDAR_CREATE = "calendar.create"
    CALENDAR_AGENDA = "calendar.agenda"
    CALENDAR_FREEBUSY = "calendar.freebusy"
    DOC_CREATE = "docs.create"
    DOC_UPDATE = "docs.update"
    DOC_SEARCH = "docs.search"
    SHEET_UPDATE = "sheets.update"
    SHEET_READ = "sheets.read"
    CONTACT_SEARCH = "contact.search"
    TASK_CREATE = "task.create"
    MAIL_SEND = "mail.send"
    BASE_RECORD_CREATE = "base.record_create"
    UNKNOWN = "unknown"


class LarkCliErrorCode(IntEnum):
    """CLI-facing aliases backed by the shared integer error-code catalog."""

    RATE_LIMIT = int(UnifiedErrorCode.RATE_LIMIT)
    API_UNSUPPORTED = int(UnifiedErrorCode.UNSUPPORTED)
    PERMISSION_DENIED = int(UnifiedErrorCode.PERMISSION_DENIED)
    RESULT_INVALID = int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
    API_ERROR = int(UnifiedErrorCode.EXECUTION_ERROR)
    TIMEOUT = int(UnifiedErrorCode.TIMEOUT)
    USER_REQUESTED = int(UnifiedErrorCode.HANDOFF_REQUIRED)
    HYBRID_TASK_REQUIRED = int(UnifiedErrorCode.HANDOFF_REQUIRED)


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
