"""Stable CUA executor contract used by the backend fallback service."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .schemas import CuaMemoryUsage, CuaRequest, CuaResponse


class CuaExecutor:
    """Compatibility wrapper around the current CUA AgentLoopRunner implementation."""

    def run(self, request: CuaRequest) -> CuaResponse:
        """Run one CUA fallback task and return the public response contract."""
        try:
            from .agent.loop_runner import AgentLoopRunner
            from .report.logger import RunLogger
        except Exception as exc:  # noqa: BLE001
            return CuaResponse(
                success=False,
                message=f"CUA runtime is unavailable: {exc}",
                history_states=[],
                memory=self._memory_usage(request),
            )

        task = self._dict_or_empty(request.task)
        action = self._dict_or_empty(request.action)
        trigger = self._dict_or_empty(request.trigger)
        memory_scope = self._normalize_memory_scope(request.memory)
        task_id = str(task.get("id", "") or "cua_task")

        logger = RunLogger(task_id, request.instruction[:80] or "cua fallback")
        runner = AgentLoopRunner(logger, self._build_llm_request_func())
        fallback_context = {
            "task_id": task_id,
            "session_id": memory_scope.get("session_id", ""),
            "chain_id": str(task.get("chain", "") or ""),
            "capability_id": str(action.get("id", "") or ""),
            "cli_error_code": trigger.get("code"),
            "cli_error_name": str(trigger.get("name", "") or ""),
            "retry_attempts": int(trigger.get("attempts", 1) or 1),
        }
        try:
            success = runner.run(
                current_goal=request.instruction,
                max_steps=int(os.getenv("CUA_MAX_STEPS", "15")),
                memory_scope=memory_scope,
                fallback_context=fallback_context,
            )
        except Exception as exc:  # noqa: BLE001
            return CuaResponse(
                success=False,
                message=f"CUA execution failed: {exc}",
                history_states=[],
                memory=CuaMemoryUsage(
                    scope=memory_scope,
                    used=getattr(runner, "used_memory_ids", []),
                    written=getattr(runner, "written_memory_ids", []),
                    summary="cua execution failed",
                ),
            )

        return CuaResponse(
            success=success,
            message="cua fallback executed" if success else "cua fallback did not finish",
            history_states=list(getattr(runner, "action_summary", [])),
            memory=CuaMemoryUsage(
                scope=memory_scope,
                used=getattr(runner, "used_memory_ids", []),
                written=getattr(runner, "written_memory_ids", []),
                summary="scoped memory used for cua fallback",
            ),
        )

    @staticmethod
    def _build_llm_request_func() -> Callable[[list[dict[str, Any]]], str]:
        def llm_request(messages: list[dict[str, Any]]) -> str:
            from .models.llm_client import post_chat_completion

            api_key = os.getenv("CUA_MODEL_API_KEY", "")
            api_url = os.getenv("CUA_MODEL_API_BASE", "")
            model = os.getenv("CUA_MODEL_NAME", "")
            if not api_key or not api_url or not model:
                raise RuntimeError("CUA_MODEL_API_KEY, CUA_MODEL_API_BASE, and CUA_MODEL_NAME are required")
            response = post_chat_completion(api_url, api_key, model, messages)
            if response.status_code != 200:
                raise RuntimeError(f"CUA model request failed: HTTP {response.status_code}: {response.text}")
            data = response.json()
            return str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()

        return llm_request

    @staticmethod
    def _memory_usage(request: CuaRequest) -> CuaMemoryUsage:
        return CuaMemoryUsage(
            scope=CuaExecutor._normalize_memory_scope(request.memory),
            used=[],
            written=[],
            summary="cua runtime unavailable before memory read",
        )

    @staticmethod
    def _dict_or_empty(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_memory_scope(memory: dict[str, Any]) -> dict[str, Any]:
        data = CuaExecutor._dict_or_empty(memory)
        return {
            "session_id": str(data.get("session", data.get("session_id", "")) or ""),
            "app_name": str(data.get("app", data.get("app_name", "")) or ""),
            "capability_id": str(data.get("action", data.get("capability_id", "")) or ""),
        }
