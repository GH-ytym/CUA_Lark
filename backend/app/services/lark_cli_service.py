"""Lark-CLI service for business adapters, normalization and error mapping."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from app.core.config import get_settings
from app.domain.enums import ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import ExecutorResult, StandardAction
from app.integrations.lark_cli_adapter import CliCallPlan, LarkCliAdapter
from shared.error_codes import cli_error_name, normalize_error_code


@dataclass(frozen=True)
class LarkCliServiceResult:
    """Normalized service result shared with orchestrator."""

    success: bool
    error_code: LarkCliErrorCode | None
    summary: str
    payload: dict[str, Any]
    plan: CliCallPlan
    executor_result: ExecutorResult | None = None


class LarkCliService:
    """Service layer around adapter planning and result normalization."""

    def __init__(self, adapter: LarkCliAdapter | None = None) -> None:
        self.adapter = adapter or LarkCliAdapter()
        self.settings = get_settings()

    def plan(self, intent: IntentType, payload: dict[str, Any]) -> CliCallPlan:
        """Build intent plan with business-level adapter routing."""
        return self.adapter.build_plan(intent=intent, payload=payload)

    def plan_action(self, action: StandardAction) -> CliCallPlan:
        """Build a CLI call plan from a standard action."""
        return self.adapter.build_plan_for_capability(
            capability_id=action.capability_id,
            payload=action.payload,
            intent=action.intent_type,
        )

    def normalize_failure(self, error_message: str) -> LarkCliErrorCode:
        """Map raw execution errors to CUA-aligned CLI error codes."""
        lower = error_message.lower()
        if "timeout" in lower or "timed out" in lower:
            return LarkCliErrorCode.TIMEOUT
        if "rate" in lower or "429" in lower:
            return LarkCliErrorCode.RATE_LIMIT
        if "permission" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
            return LarkCliErrorCode.PERMISSION_DENIED
        if "unsupported" in lower or "not support" in lower:
            return LarkCliErrorCode.API_UNSUPPORTED
        if "invalid result" in lower or "empty result" in lower:
            return LarkCliErrorCode.RESULT_INVALID
        return LarkCliErrorCode.API_ERROR

    def execute(self, intent: IntentType, payload: dict[str, Any], dry_run: bool = False) -> LarkCliServiceResult:
        """Backward-compatible intent execution API."""
        action = StandardAction(
            capability_id=self.adapter.build_plan(intent=intent, payload=payload).capability_id,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=intent,
        )
        plan = self.plan_action(action)
        executor_result = self.execute_action(action=action, dry_run=dry_run)
        return self._legacy_result_from_executor_result(plan=plan, result=executor_result)

    def execute_action(self, action: StandardAction, dry_run: bool = False) -> ExecutorResult:
        """Execute a standard action through lark-cli and return one unified result."""
        plan = self.plan_action(action)
        use_dry_run = dry_run or bool(action.payload.get("dry_run", False))
        steps: list[dict[str, Any]] = []
        if not plan.invocations:
            return self._executor_failure_result(
                summary="capability is not supported by current CLI registry",
                error_code=LarkCliErrorCode.API_UNSUPPORTED,
                payload=self._build_payload(
                    plan=plan,
                    dry_run=use_dry_run,
                    steps=steps,
                    error=self._build_error_info(
                        error_code=LarkCliErrorCode.API_UNSUPPORTED,
                        message="capability is not supported by current CLI registry",
                        detail={"capability_id": action.capability_id.value},
                    ),
                ),
            )
        cli_bin = self._resolve_cli_bin(self.settings.lark_cli_path)
        workdir = self._resolve_workdir(self.settings.lark_cli_workdir)
        timeout = max(1, int(self.settings.lark_cli_timeout_seconds))
        started_all = time.perf_counter()
        for invocation in plan.invocations:
            try:
                argv = self.adapter.build_command(invocation=invocation, cli_bin=cli_bin, dry_run=use_dry_run)
            except ValueError as exc:
                error = self._build_error_info(
                    error_code=LarkCliErrorCode.RESULT_INVALID,
                    message=f"invalid cli payload: {exc}",
                    detail={
                        "tool_family": invocation.tool_family,
                        "operation": invocation.operation,
                    },
                )
                return self._executor_failure_result(
                    summary=f"invalid cli payload: {exc}",
                    error_code=LarkCliErrorCode.RESULT_INVALID,
                    payload=self._build_payload(plan=plan, dry_run=use_dry_run, steps=steps, error=error),
                    duration_ms=self._elapsed_ms(started_all),
                )
            rendered = self.adapter.stringify_command(argv)
            started = time.perf_counter()
            try:
                proc = subprocess.run(
                    argv,
                    check=False,
                    capture_output=True,
                    text=False,
                    timeout=timeout,
                    cwd=workdir,
                )
            except subprocess.TimeoutExpired as exc:
                error = self._build_error_info(
                    error_code=LarkCliErrorCode.TIMEOUT,
                    message=f"cli execution timeout: {timeout}s",
                    detail={"command": rendered, "timeout": timeout, "stderr": str(exc)},
                )
                return self._executor_failure_result(
                    summary=f"cli execution timeout: {timeout}s",
                    error_code=LarkCliErrorCode.TIMEOUT,
                    payload=self._build_payload(plan=plan, dry_run=use_dry_run, steps=steps, error=error),
                    duration_ms=self._elapsed_ms(started_all),
                )
            except Exception as exc:  # noqa: BLE001
                code = self.normalize_failure(str(exc))
                error = self._build_error_info(
                    error_code=code,
                    message=f"cli invocation failed before execution: {exc}",
                    detail={"command": rendered},
                )
                return self._executor_failure_result(
                    summary=f"cli invocation failed before execution: {exc}",
                    error_code=code,
                    payload=self._build_payload(plan=plan, dry_run=use_dry_run, steps=steps, error=error),
                    duration_ms=self._elapsed_ms(started_all),
                )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout_text = self._decode_output(proc.stdout)
            stderr_text = self._decode_output(proc.stderr)
            parsed = self._parse_cli_output(stdout_text)
            step = {
                "tool_family": invocation.tool_family,
                "operation": invocation.operation,
                "command": rendered,
                "exit_code": proc.returncode,
                "duration_ms": duration_ms,
                "stdout": stdout_text.strip(),
                "stderr": stderr_text.strip(),
                "parsed": parsed,
            }
            steps.append(step)
            if proc.returncode != 0:
                error_text = stderr_text.strip() or stdout_text.strip() or "cli returned non-zero"
                code = self.normalize_failure(error_text)
                error = self._build_error_info(
                    error_code=code,
                    message="cli command failed",
                    detail={"last_error": error_text},
                )
                return self._executor_failure_result(
                    summary="cli command failed",
                    error_code=code,
                    payload=self._build_payload(plan=plan, dry_run=use_dry_run, steps=steps, error=error),
                    duration_ms=self._elapsed_ms(started_all),
                )
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary=f"executed {len(plan.invocations)} cli invocation(s)",
            payload=self._build_payload(plan=plan, dry_run=use_dry_run, steps=steps, error=None),
            duration_ms=self._elapsed_ms(started_all),
        )

    def simulate_execute(self, intent: IntentType, payload: dict[str, Any]) -> LarkCliServiceResult:
        """Backward-compatible alias. Day4 now uses real CLI execution path."""
        return self.execute(intent=intent, payload=payload, dry_run=bool(payload.get("dry_run", True)))

    def _success_result(
        self,
        plan: CliCallPlan,
        dry_run: bool,
        steps: list[dict[str, Any]],
        summary: str,
    ) -> LarkCliServiceResult:
        return LarkCliServiceResult(
            success=True,
            error_code=None,
            summary=summary,
            payload=self._build_payload(plan=plan, dry_run=dry_run, steps=steps, error=None),
            plan=plan,
        )

    def _legacy_result_from_executor_result(
        self,
        plan: CliCallPlan,
        result: ExecutorResult,
    ) -> LarkCliServiceResult:
        normalized = normalize_error_code(result.error_code)
        error_code = None
        if normalized is not None:
            try:
                error_code = LarkCliErrorCode(int(normalized))
            except ValueError:
                error_code = None
        return LarkCliServiceResult(
            success=result.success,
            error_code=error_code,
            summary=result.summary,
            payload=result.payload,
            plan=plan,
            executor_result=result,
        )

    @staticmethod
    def _executor_failure_result(
        summary: str,
        error_code: LarkCliErrorCode,
        payload: dict[str, Any],
        duration_ms: float = 0.0,
    ) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary=summary,
            payload=payload,
            error_code=int(error_code),
            duration_ms=duration_ms,
        )

    def _failure_result(
        self,
        plan: CliCallPlan,
        dry_run: bool,
        steps: list[dict[str, Any]],
        error_code: LarkCliErrorCode,
        summary: str,
        detail: dict[str, Any] | None = None,
    ) -> LarkCliServiceResult:
        error = self._build_error_info(error_code=error_code, message=summary, detail=detail)
        return LarkCliServiceResult(
            success=False,
            error_code=error_code,
            summary=summary,
            payload=self._build_payload(plan=plan, dry_run=dry_run, steps=steps, error=error),
            plan=plan,
        )

    @staticmethod
    def _build_error_info(
        error_code: LarkCliErrorCode,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "code": int(error_code),
            "name": cli_error_name(error_code),
            "message": message,
            "detail": detail or {},
        }

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    @staticmethod
    def _build_payload(
        plan: CliCallPlan,
        dry_run: bool,
        steps: list[dict[str, Any]],
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "domain": plan.domain.value,
            "dry_run": dry_run,
            "steps": steps,
            "error": error,
        }

    @staticmethod
    def _parse_cli_output(stdout: str | bytes | None) -> dict[str, Any]:
        text = LarkCliService._decode_output(stdout).strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                return {"raw": text}
        return {"raw": text}

    @staticmethod
    def _resolve_workdir(raw_workdir: str) -> str | None:
        if not raw_workdir:
            return None
        text = raw_workdir.strip()
        if not text:
            return None
        path = Path(text)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
            path = project_root / path
        return str(path) if path.exists() else None

    @staticmethod
    def _resolve_cli_bin(raw_cli_path: str) -> str:
        text = (raw_cli_path or "").strip() or "lark-cli"
        if Path(text).is_file():
            return text
        which_path = shutil.which(text)
        if which_path:
            return which_path
        cmd_fallback = shutil.which(f"{text}.cmd")
        if cmd_fallback:
            return cmd_fallback
        return text

    @staticmethod
    def _decode_output(content: str | bytes | None) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        for encoding in ("utf-8", "gbk", "cp936"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
