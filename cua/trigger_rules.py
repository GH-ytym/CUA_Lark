"""Trigger and abort rules for CLI-to-CUA handoff."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

from shared.error_codes import (
    CLI_TRIGGER_ERROR_CODES,
    CUA_ABORT_ERROR_CODES,
    UnifiedErrorCode,
    normalize_error_code,
)


class LarkCliError(IntEnum):
    """Backward-compatible CLI aliases backed by the shared integer catalog."""

    RATE_LIMIT = int(UnifiedErrorCode.RATE_LIMIT)
    API_UNSUPPORTED = int(UnifiedErrorCode.UNSUPPORTED)
    PERMISSION_DENIED = int(UnifiedErrorCode.PERMISSION_DENIED)
    RESULT_INVALID = int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
    API_ERROR = int(UnifiedErrorCode.EXECUTION_ERROR)
    TIMEOUT = int(UnifiedErrorCode.TIMEOUT)
    USER_REQUESTED = int(UnifiedErrorCode.HANDOFF_REQUIRED)
    HYBRID_TASK_REQUIRED = int(UnifiedErrorCode.HANDOFF_REQUIRED)


class CuaAbortReason(IntEnum):
    """Backward-compatible CUA aliases backed by the shared integer catalog."""

    LOW_CONFIDENCE = int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE)
    TIMEOUT = int(UnifiedErrorCode.TIMEOUT)
    INTERFACE_CHANGED = int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE)
    MAX_RETRY_EXCEEDED = int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE)
    SECURITY_RISK = int(UnifiedErrorCode.SECURITY_BLOCKED)
    USER_INTERRUPTED = int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE)
    MULTI_MONITOR_UNSUPPORTED = int(UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE)


class CuaConfig(BaseModel):
    """Configurable CUA safety and fallback parameters."""

    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_retry_count: int = Field(default=3, ge=1, le=10)
    operation_timeout: int = Field(default=30, ge=5, le=300)
    task_total_timeout: int = Field(default=300, ge=60, le=3600)
    dpi_scale_factor: float = Field(default=0.0, ge=0.0, le=5.0)
    enable_user_interrupt_detection: bool = Field(default=True)
    enable_security_check: bool = Field(default=True)
    fallback_strategy_level: int = Field(default=2, ge=0, le=3)
    sensitive_operation_blacklist: list[str] = Field(
        default_factory=lambda: ["password", "支付", "转账", "删除", "卸载", "格式化"]
    )


class TriggerRuleEvaluator:
    """Evaluate whether CLI should hand off to CUA and when CUA should abort."""

    def __init__(self, config: CuaConfig | None = None):
        self.config = config or CuaConfig()

    def should_trigger_cua(self, cli_result: dict[str, Any]) -> bool:
        """Return whether one CLI result should trigger CUA fallback."""

        if self.config.fallback_strategy_level == 0:
            return False
        if self.config.fallback_strategy_level == 3:
            return True

        error_code = normalize_error_code(cli_result.get("error_code"))
        if error_code is not None and int(error_code) in CLI_TRIGGER_ERROR_CODES:
            return True

        if cli_result.get("success") and not cli_result.get("data"):
            return self.config.fallback_strategy_level >= 2
        return False

    def should_abort_execution(self, execution_context: dict[str, Any]) -> UnifiedErrorCode | None:
        """Return one shared abort code when CUA must stop."""

        if execution_context.get("confidence", 1.0) < self.config.confidence_threshold:
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        if execution_context.get("retry_count", 0) >= self.config.max_retry_count:
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        if execution_context.get("operation_elapsed", 0) >= self.config.operation_timeout:
            return UnifiedErrorCode.TIMEOUT
        if execution_context.get("task_elapsed", 0) >= self.config.task_total_timeout:
            return UnifiedErrorCode.TIMEOUT
        if self.config.enable_user_interrupt_detection and execution_context.get("user_interrupted"):
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        if self.config.enable_security_check:
            operation = str(execution_context.get("operation", "")).lower()
            if any(keyword in operation for keyword in self.config.sensitive_operation_blacklist):
                return UnifiedErrorCode.SECURITY_BLOCKED
        multi_monitor_unsupported = execution_context.get("multi_monitor_unsupported")
        if multi_monitor_unsupported:
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        return None


__all__ = [
    "CLI_TRIGGER_ERROR_CODES",
    "CUA_ABORT_ERROR_CODES",
    "CuaAbortReason",
    "CuaConfig",
    "LarkCliError",
    "TriggerRuleEvaluator",
]
