"""Shared integer error-code catalog used by backend and CUA."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class UnifiedErrorCode(IntEnum):
    """Single source of truth for execution error codes."""

    NONE = 0
    RATE_LIMIT = 1
    UNSUPPORTED = 2
    PERMISSION_DENIED = 3
    INVALID_INPUT_OR_RESULT = 4
    EXECUTION_ERROR = 5
    TIMEOUT = 6
    HANDOFF_REQUIRED = 7
    UI_ENVIRONMENT_UNSAFE = 8
    SECURITY_BLOCKED = 9


@dataclass(frozen=True)
class ErrorCodeDescriptor:
    """Serializable description for one shared error code."""

    code: int
    name: str
    description: str


_ERROR_CODE_DESCRIPTIONS: dict[UnifiedErrorCode, str] = {
    UnifiedErrorCode.NONE: "Success or no error.",
    UnifiedErrorCode.RATE_LIMIT: "The upstream service rejected the request due to rate limiting.",
    UnifiedErrorCode.UNSUPPORTED: "The requested capability or runtime environment is unsupported.",
    UnifiedErrorCode.PERMISSION_DENIED: "The action was blocked by permissions or authentication.",
    UnifiedErrorCode.INVALID_INPUT_OR_RESULT: "Required input was missing or the returned result was invalid.",
    UnifiedErrorCode.EXECUTION_ERROR: "Execution failed for an internal or uncategorized reason.",
    UnifiedErrorCode.TIMEOUT: "The action exceeded its timeout budget.",
    UnifiedErrorCode.HANDOFF_REQUIRED: "The task must hand off to a different executor.",
    UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE: "The GUI environment is unstable or unsafe to continue.",
    UnifiedErrorCode.SECURITY_BLOCKED: "Execution was blocked by a security safeguard.",
}

ERROR_CODE_CATALOG: tuple[ErrorCodeDescriptor, ...] = tuple(
    ErrorCodeDescriptor(
        code=int(code),
        name=code.name,
        description=_ERROR_CODE_DESCRIPTIONS[code],
    )
    for code in UnifiedErrorCode
)

CUA_ABORT_ERROR_CODES: tuple[int, ...] = (
    int(UnifiedErrorCode.TIMEOUT),
    int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE),
    int(UnifiedErrorCode.SECURITY_BLOCKED),
)

CLI_LEGACY_ERROR_NAME_TO_CODE: dict[str, UnifiedErrorCode] = {
    "rate_limit_exceeded": UnifiedErrorCode.RATE_LIMIT,
    "api_unsupported": UnifiedErrorCode.UNSUPPORTED,
    "permission_denied": UnifiedErrorCode.PERMISSION_DENIED,
    "result_invalid": UnifiedErrorCode.INVALID_INPUT_OR_RESULT,
    "api_internal_error": UnifiedErrorCode.EXECUTION_ERROR,
    "operation_timeout": UnifiedErrorCode.TIMEOUT,
    "user_requested": UnifiedErrorCode.HANDOFF_REQUIRED,
    "hybrid_task_required": UnifiedErrorCode.HANDOFF_REQUIRED,
}

CLI_ERROR_CODE_TO_DEFAULT_NAME: dict[UnifiedErrorCode, str] = {
    UnifiedErrorCode.RATE_LIMIT: "rate_limit_exceeded",
    UnifiedErrorCode.UNSUPPORTED: "api_unsupported",
    UnifiedErrorCode.PERMISSION_DENIED: "permission_denied",
    UnifiedErrorCode.INVALID_INPUT_OR_RESULT: "result_invalid",
    UnifiedErrorCode.EXECUTION_ERROR: "api_internal_error",
    UnifiedErrorCode.TIMEOUT: "operation_timeout",
    UnifiedErrorCode.HANDOFF_REQUIRED: "hybrid_task_required",
}

CUA_ABORT_REASON_NAME_TO_CODE: dict[str, UnifiedErrorCode] = {
    "low_confidence": UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE,
    "operation_timeout": UnifiedErrorCode.TIMEOUT,
    "interface_unexpectedly_changed": UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE,
    "max_retry_exceeded": UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE,
    "security_risk_detected": UnifiedErrorCode.SECURITY_BLOCKED,
    "user_interrupted": UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE,
    "multi_monitor_unsupported": UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE,
}

CUA_ERROR_CODE_TO_DEFAULT_NAME: dict[UnifiedErrorCode, str] = {
    UnifiedErrorCode.TIMEOUT: "operation_timeout",
    UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE: "interface_unexpectedly_changed",
    UnifiedErrorCode.SECURITY_BLOCKED: "security_risk_detected",
    UnifiedErrorCode.EXECUTION_ERROR: "cua_execution_error",
}


def normalize_error_code(value: Any) -> UnifiedErrorCode | None:
    """Normalize int, enum, or legacy string inputs into one shared enum."""

    if value is None or value == "":
        return None
    if isinstance(value, UnifiedErrorCode):
        return value
    if isinstance(value, IntEnum):
        try:
            return UnifiedErrorCode(int(value))
        except ValueError:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text in CLI_LEGACY_ERROR_NAME_TO_CODE:
            return CLI_LEGACY_ERROR_NAME_TO_CODE[text]
        if text in CUA_ABORT_REASON_NAME_TO_CODE:
            return CUA_ABORT_REASON_NAME_TO_CODE[text]
        try:
            return UnifiedErrorCode(int(text))
        except ValueError:
            return None
    try:
        return UnifiedErrorCode(int(value))
    except (TypeError, ValueError):
        return None


def cli_error_name(value: Any) -> str:
    """Return the canonical debug name for one CLI-side error code."""

    code = normalize_error_code(value)
    if code is None:
        return ""
    return CLI_ERROR_CODE_TO_DEFAULT_NAME.get(code, "")


def cua_error_name(value: Any) -> str:
    """Return the canonical debug name for one CUA-side error code."""

    code = normalize_error_code(value)
    if code is None:
        return ""
    return CUA_ERROR_CODE_TO_DEFAULT_NAME.get(code, "")


def error_code_catalog_payload() -> list[dict[str, object]]:
    """Return the shared error-code catalog in JSON-serializable form."""

    return [
        {"code": item.code, "name": item.name, "description": item.description}
        for item in ERROR_CODE_CATALOG
    ]
