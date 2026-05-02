"""CUA fallback service that bridges the backend orchestrator to the desktop executor."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType
from app.domain.models import ExecutorResult, StandardAction


class CuaService:
    """Execute a CUA fallback request and normalize its result for the orchestrator."""

    def execute_fallback(
        self,
        *,
        action: StandardAction,
        raw_message: str,
        task_id: str,
        cli_error_code: str,
        cli_payload: dict[str, object] | None = None,
    ) -> ExecutorResult:
        """Trigger the desktop CUA flow after CLI failure and return one unified result."""
        request_payload = self._build_request_payload(action=action, raw_message=raw_message)
        try:
            executor_cls, request_cls = self._load_executor_components()
            executor = executor_cls()
            response = executor.run(request_cls(**request_payload))
        except Exception as exc:  # noqa: BLE001
            return ExecutorResult(
                executor=ExecutorType.CUA,
                success=False,
                status=ExecutionStatus.FAILED,
                summary=f"cua fallback failed before execution: {exc}",
                payload={
                    "mode": "cua_fallback",
                    "task_id": task_id,
                    "request": request_payload,
                    "triggered_by": {"cli_error_code": cli_error_code},
                    "cli_payload": cli_payload or {},
                    "error": {"message": str(exc)},
                },
            )

        response_payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        success = bool(getattr(response, "success", False))
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=success,
            status=ExecutionStatus.COMPLETED if success else ExecutionStatus.FAILED,
            summary=str(getattr(response, "message", "")).strip() or "cua fallback finished",
            payload={
                "mode": "cua_fallback",
                "task_id": task_id,
                "request": request_payload,
                "triggered_by": {"cli_error_code": cli_error_code},
                "cli_payload": cli_payload or {},
                "cua_response": response_payload,
            },
        )

    @staticmethod
    def _build_request_payload(action: StandardAction, raw_message: str) -> dict[str, str]:
        return {
            "instruction": CuaService._instruction_from_action(action=action, raw_message=raw_message),
            "app_name": "飞书",
        }

    @staticmethod
    def _instruction_from_action(action: StandardAction, raw_message: str) -> str:
        payload = action.payload
        if action.capability_id == CapabilityId.IM_MESSAGE_SEND:
            target = (
                str(payload.get("resolved_name", "")).strip()
                or str(payload.get("chat_hint", "")).strip()
                or "目标对象"
            )
            text = str(payload.get("text", "")).strip()
            if text:
                return f"请在飞书中向{target}发送消息：{text}"
        return raw_message.strip() or action.capability_id.value

    @staticmethod
    def _load_executor_components() -> tuple[type[Any], type[Any]]:
        project_root = Path(__file__).resolve().parents[3]
        project_root_text = str(project_root)
        if project_root_text not in sys.path:
            sys.path.append(project_root_text)

        from cua.executor import CuaExecutor
        from cua.schemas import CuaRequest

        return CuaExecutor, CuaRequest
