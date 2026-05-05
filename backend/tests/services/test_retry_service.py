from app.services.retry_service import RetryService
from shared.error_codes import UnifiedErrorCode


def test_retry_service_retries_transient_codes_until_success() -> None:
    service = RetryService()
    calls = 0

    def operation() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"success": False, "error_code": int(UnifiedErrorCode.TIMEOUT)}
        return {"success": True, "error_code": None}

    result = service.run(
        operation,
        is_success=lambda item: bool(item["success"]),
        error_code=lambda item: item["error_code"],  # type: ignore[return-value]
    )

    assert calls == 2
    assert result["success"] is True


def test_retry_service_does_not_retry_permission_or_invalid_payload() -> None:
    service = RetryService()
    calls = 0

    def operation() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": False, "error_code": int(UnifiedErrorCode.PERMISSION_DENIED)}

    result = service.run(
        operation,
        is_success=lambda item: bool(item["success"]),
        error_code=lambda item: item["error_code"],  # type: ignore[return-value]
    )

    assert calls == 1
    assert result["error_code"] == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert service.should_retry(int(UnifiedErrorCode.RATE_LIMIT)) is True
    assert service.should_retry(int(UnifiedErrorCode.EXECUTION_ERROR)) is True
    assert service.should_retry(int(UnifiedErrorCode.TIMEOUT)) is True
    assert service.should_retry(int(UnifiedErrorCode.PERMISSION_DENIED)) is False
    assert service.should_retry(int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)) is False
