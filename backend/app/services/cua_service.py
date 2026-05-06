"""CUA fallback service that bridges the backend orchestrator to the desktop executor."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType
from app.domain.models import ExecutorResult, StandardAction
from shared.error_codes import UnifiedErrorCode, cli_error_name, cua_error_name


class CuaService:
    """Execute a CUA fallback request and normalize its result for the orchestrator."""

    def execute_fallback(
        self,
        *,
        action: StandardAction,
        raw_message: str,
        task_id: str,
        session_id: str = "",
        chain_id: str = "",
        cli_error_code: int | None,
        cli_payload: dict[str, object] | None = None,
        retry_attempts: int = 1,
        trigger_source: str = "cli",
    ) -> ExecutorResult:
        """Trigger the desktop CUA flow after CLI failure and return one unified result."""
        request_payload = self._build_request_payload(
            action=action,
            raw_message=raw_message,
            task_id=task_id,
            session_id=session_id,
            chain_id=chain_id or task_id,
            cli_error_code=cli_error_code,
            cli_payload=cli_payload,
            retry_attempts=retry_attempts,
            trigger_source=trigger_source,
        )
        fallback_request = self._build_fallback_request(
            action=action,
            raw_message=raw_message,
            task_id=task_id,
            session_id=session_id,
            chain_id=chain_id or task_id,
            cli_error_code=cli_error_code,
            cli_payload=cli_payload,
            request_payload=request_payload,
            trigger_source=trigger_source,
        )
        try:
            executor_cls, request_cls = self._load_executor_components()
            executor = executor_cls()
            response = executor.run(request_cls(**request_payload))
        except Exception as exc:  # noqa: BLE001
            error_code = int(UnifiedErrorCode.EXECUTION_ERROR)
            error_message = f"cua fallback failed before execution: {exc}"
            return ExecutorResult(
                executor=ExecutorType.CUA,
                success=False,
                status=ExecutionStatus.FAILED,
                summary=error_message,
                payload={
                    "mode": "cua_fallback",
                    "task_id": task_id,
                    "fallback_request": fallback_request,
                    "request": request_payload,
                    "triggered_by": self._build_triggered_by(cli_error_code, source=trigger_source),
                    "cli_payload": cli_payload or {},
                    "cua": {"memory": self._empty_memory_payload(request_payload)},
                    "error": {
                        "code": error_code,
                        "name": cua_error_name(error_code),
                        "message": error_message,
                        "detail": {"exception": str(exc)},
                    },
                },
                error_code=error_code,
            )

        response_payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        success = bool(getattr(response, "success", False))
        summary = str(getattr(response, "message", "")).strip() or "cua fallback finished"
        error_code = None if success else int(self._map_failure_code(response_payload=response_payload, summary=summary))
        payload: dict[str, object] = {
            "mode": "cua_fallback",
            "task_id": task_id,
            "fallback_request": fallback_request,
            "request": request_payload,
            "triggered_by": self._build_triggered_by(cli_error_code, source=trigger_source),
            "cli_payload": cli_payload or {},
            "cua_response": response_payload,
            "cua": {"memory": self._extract_memory_payload(response_payload, request_payload)},
        }
        if error_code is not None:
            payload["error"] = {
                "code": error_code,
                "name": cua_error_name(error_code),
                "message": summary,
                "detail": {"diagnosis_report": response_payload.get("diagnosis_report")},
            }
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=success,
            status=ExecutionStatus.COMPLETED if success else ExecutionStatus.FAILED,
            summary=summary,
            payload=payload,
            error_code=error_code,
        )

    @staticmethod
    def _build_request_payload(
        *,
        action: StandardAction,
        raw_message: str,
        task_id: str,
        session_id: str,
        chain_id: str,
        cli_error_code: int | None,
        cli_payload: dict[str, object] | None,
        retry_attempts: int,
        trigger_source: str,
    ) -> dict[str, object]:
        cli_error_name_text = cli_error_name(cli_error_code)
        action_id = action.capability_id.value
        return {
            "instruction": CuaService._instruction_from_action(action=action, raw_message=raw_message),
            "app": "飞书",
            "task": {
                "id": task_id,
                "session": session_id,
                "chain": chain_id,
            },
            "action": {
                "id": action_id,
                "payload": CuaService._build_cua_action_payload(action),
            },
            "trigger": {
                "source": CuaService._normalize_trigger_source(trigger_source),
                "code": cli_error_code,
                "name": cli_error_name_text,
                "attempts": max(1, int(retry_attempts)),
                "summary": CuaService._build_trigger_summary(
                    cli_error_name=cli_error_name_text,
                    cli_payload=cli_payload,
                ),
            },
            "memory": {
                "session": session_id,
                "app": "飞书",
                "action": action_id,
            },
        }

    @staticmethod
    def _build_fallback_request(
        *,
        action: StandardAction,
        raw_message: str,
        task_id: str,
        session_id: str,
        chain_id: str,
        cli_error_code: int | None,
        cli_payload: dict[str, object] | None,
        request_payload: dict[str, object],
        trigger_source: str,
    ) -> dict[str, object]:
        return {
            "task_id": task_id,
            "session_id": session_id,
            "chain_id": chain_id,
            "raw_message": raw_message,
            "standard_action": action.model_dump(),
            "capability_id": action.capability_id.value,
            "cli_error_code": cli_error_code,
            "cli_error_name": cli_error_name(cli_error_code),
            "cli_payload": cli_payload or {},
            "triggered_by": CuaService._build_triggered_by(cli_error_code, source=trigger_source),
            "cua_request": request_payload,
        }

    @staticmethod
    def _build_triggered_by(cli_error_code: int | None, source: str = "cli") -> dict[str, object]:
        return {
            "source": CuaService._normalize_trigger_source(source),
            "cli_error_code": cli_error_code,
            "cli_error_name": cli_error_name(cli_error_code),
        }

    @staticmethod
    def _normalize_trigger_source(source: str) -> str:
        normalized = str(source).strip().lower()
        return normalized if normalized in {"cli", "structured"} else "cli"

    @staticmethod
    def _empty_memory_payload(request_payload: dict[str, object]) -> dict[str, object]:
        scope = request_payload.get("memory")
        return {
            "scope": scope if isinstance(scope, dict) else {},
            "used": [],
            "written": [],
            "summary": "",
        }

    @staticmethod
    def _extract_memory_payload(
        response_payload: dict[str, object],
        request_payload: dict[str, object],
    ) -> dict[str, object]:
        memory = response_payload.get("memory")
        if isinstance(memory, dict):
            scope = memory.get("scope")
            return {
                "scope": scope if isinstance(scope, dict) else request_payload.get("memory", {}),
                "used": memory.get("used", memory.get("used_ids", [])),
                "written": memory.get("written", memory.get("written_ids", [])),
                "summary": memory.get("summary", ""),
            }
        return CuaService._empty_memory_payload(request_payload)

    @staticmethod
    def _build_cua_action_payload(action: StandardAction) -> dict[str, object]:
        """Return only task-relevant fields for the CUA public contract."""
        omitted = {"resolution_candidates", "resolution_method", "idempotency_key", "dry_run"}
        return {
            key: value
            for key, value in action.payload.items()
            if key not in omitted and value not in ("", None, [], {})
        }

    @staticmethod
    def _build_trigger_summary(
        *,
        cli_error_name: str,
        cli_payload: dict[str, object] | None,
    ) -> str:
        if not isinstance(cli_payload, dict):
            return cli_error_name
        summary = str(cli_payload.get("summary", "")).strip()
        if summary:
            return summary
        error = cli_payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message", "")).strip()
            if message:
                return message
            name = str(error.get("name", "")).strip()
            if name:
                return name
        return cli_error_name

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
    def _map_failure_code(response_payload: dict[str, object], summary: str) -> UnifiedErrorCode:
        diagnosis = response_payload.get("diagnosis_report")
        diagnosis_type = ""
        if isinstance(diagnosis, dict):
            diagnosis_type = str(diagnosis.get("error_type", "")).strip().upper()

        lowered_summary = summary.lower()
        if "timeout" in lowered_summary or "超时" in summary:
            return UnifiedErrorCode.TIMEOUT
        if diagnosis_type == "PERMISSION_BLOCKED":
            return UnifiedErrorCode.SECURITY_BLOCKED
        if "security" in lowered_summary or "风险" in summary or "安全" in summary:
            return UnifiedErrorCode.SECURITY_BLOCKED
        if diagnosis_type in {"INTERFACE_CHANGED", "COORDINATE_OFFSET", "ELEMENT_NOT_FOUND"}:
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        if (
            "interrupted" in lowered_summary
            or "retry" in lowered_summary
            or "confidence" in lowered_summary
            or "界面" in summary
            or "置信度" in summary
            or "中断" in summary
            or "重试" in summary
        ):
            return UnifiedErrorCode.UI_ENVIRONMENT_UNSAFE
        return UnifiedErrorCode.EXECUTION_ERROR

    @staticmethod
    def _load_executor_components() -> tuple[type[Any], type[Any]]:
        project_root = Path(__file__).resolve().parents[3]
        project_root_text = str(project_root)
        if project_root_text not in sys.path:
            sys.path.append(project_root_text)

        from cua.executor import CuaExecutor
        from cua.schemas import CuaRequest

        return CuaExecutor, CuaRequest
