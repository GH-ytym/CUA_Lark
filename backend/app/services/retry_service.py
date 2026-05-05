"""Retry policy for Day-8 CLI execution resilience."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from typing import TypeVar

from shared.error_codes import UnifiedErrorCode, normalize_error_code


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Small deterministic retry policy used by the in-memory orchestrator."""

    max_attempts: int = 2
    backoff_seconds: float = 0.0
    retryable_error_codes: tuple[int, ...] = (
        int(UnifiedErrorCode.RATE_LIMIT),
        int(UnifiedErrorCode.EXECUTION_ERROR),
        int(UnifiedErrorCode.TIMEOUT),
    )


class RetryService:
    """Run one operation with a bounded retry policy based on unified error codes."""

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        self.policy = policy or RetryPolicy()

    def run(
        self,
        operation: Callable[[], T],
        *,
        is_success: Callable[[T], bool],
        error_code: Callable[[T], int | None],
    ) -> T:
        """Execute operation until success, non-retryable failure, or attempts are exhausted."""
        attempts = max(1, int(self.policy.max_attempts))
        last_result: T | None = None
        for attempt in range(1, attempts + 1):
            result = operation()
            last_result = result
            if is_success(result):
                return result
            if attempt >= attempts:
                return result
            if not self.should_retry(error_code(result)):
                return result
            if self.policy.backoff_seconds > 0:
                sleep(self.policy.backoff_seconds)
        if last_result is None:  # pragma: no cover - defensive; loop always runs.
            raise RuntimeError("retry operation did not run")
        return last_result

    def should_retry(self, code: int | None) -> bool:
        """Return whether one unified error code should be retried."""
        normalized = normalize_error_code(code)
        return normalized is not None and int(normalized) in self.policy.retryable_error_codes
