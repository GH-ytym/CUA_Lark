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
from app.domain.enums import IntentType, LarkCliErrorCode
from app.integrations.lark_cli_adapter import CliCallPlan, LarkCliAdapter


@dataclass(frozen=True)
class LarkCliServiceResult:
    """Normalized service result shared with orchestrator."""

    success: bool
    error_code: LarkCliErrorCode | None
    summary: str
    payload: dict[str, Any]
    plan: CliCallPlan


class LarkCliService:
    """Service layer around adapter planning and result normalization."""

    def __init__(self, adapter: LarkCliAdapter | None = None) -> None:
        self.adapter = adapter or LarkCliAdapter()
        self.settings = get_settings()

    def plan(self, intent: IntentType, payload: dict[str, Any]) -> CliCallPlan:
        """Build intent plan with business-level adapter routing."""
        return self.adapter.build_plan(intent=intent, payload=payload)

    def normalize_failure(self, error_message: str) -> LarkCliErrorCode:
        """Map raw execution errors to CUA-aligned CLI error codes."""
        lower = error_message.lower()
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
        """Execute planned lark-cli command(s) and normalize outputs."""
        plan = self.plan(intent=intent, payload=payload)
        if not plan.invocations:
            return LarkCliServiceResult(
                success=False,
                error_code=LarkCliErrorCode.API_UNSUPPORTED,
                summary="intent is not supported by current CLI business adapters",
                payload={},
                plan=plan,
            )
        steps: list[dict[str, Any]] = []
        cli_bin = self._resolve_cli_bin(self.settings.lark_cli_path)
        use_dry_run = dry_run or bool(payload.get("dry_run", False))
        workdir = self._resolve_workdir(self.settings.lark_cli_workdir)
        timeout = max(1, int(self.settings.lark_cli_timeout_seconds))
        for invocation in plan.invocations:
            try:
                argv = self.adapter.build_command(invocation=invocation, cli_bin=cli_bin, dry_run=use_dry_run)
            except ValueError as exc:
                return LarkCliServiceResult(
                    success=False,
                    error_code=LarkCliErrorCode.RESULT_INVALID,
                    summary=f"invalid cli payload: {exc}",
                    payload={"domain": plan.domain.value},
                    plan=plan,
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
                return LarkCliServiceResult(
                    success=False,
                    error_code=LarkCliErrorCode.RATE_LIMIT,
                    summary=f"cli execution timeout: {timeout}s",
                    payload={"command": rendered, "timeout": timeout, "stderr": str(exc)},
                    plan=plan,
                )
            except Exception as exc:  # noqa: BLE001
                code = self.normalize_failure(str(exc))
                return LarkCliServiceResult(
                    success=False,
                    error_code=code,
                    summary=f"cli invocation failed before execution: {exc}",
                    payload={"command": rendered},
                    plan=plan,
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
                return LarkCliServiceResult(
                    success=False,
                    error_code=self.normalize_failure(error_text),
                    summary="cli command failed",
                    payload={"domain": plan.domain.value, "steps": steps},
                    plan=plan,
                )
        return LarkCliServiceResult(
            success=True,
            error_code=None,
            summary=f"executed {len(plan.invocations)} cli invocation(s)",
            payload={"domain": plan.domain.value, "dry_run": use_dry_run, "steps": steps},
            plan=plan,
        )

    def simulate_execute(self, intent: IntentType, payload: dict[str, Any]) -> LarkCliServiceResult:
        """Backward-compatible alias. Day4 now uses real CLI execution path."""
        return self.execute(intent=intent, payload=payload, dry_run=bool(payload.get("dry_run", True)))

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
