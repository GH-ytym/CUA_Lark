"""LLM-assisted diagnosis before falling back from CLI to CUA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.models import ExecutorResult, StandardAction
from app.services.intent_service import IntentService
from shared.error_codes import UnifiedErrorCode, cli_error_name, normalize_error_code

DiagnosisCategory = Literal[
    "input_or_syntax_error",
    "permission_denied",
    "cli_unsupported",
    "runtime_or_network_error",
    "requires_ui_context",
    "unknown",
]


@dataclass(frozen=True)
class CliFailureDiagnosis:
    """A compact decision used by the orchestrator before CUA handoff."""

    category: DiagnosisCategory
    should_fallback_to_cua: bool
    confidence: float
    reason: str
    user_message: str
    source: str = "qwen"
    raw_payload: dict[str, object] | None = None

    def model_dump(self) -> dict[str, object]:
        """Return a JSON-serializable payload without depending on pydantic."""
        return {
            "category": self.category,
            "should_fallback_to_cua": self.should_fallback_to_cua,
            "confidence": self.confidence,
            "reason": self.reason,
            "user_message": self.user_message,
            "source": self.source,
            "raw_payload": self.raw_payload or {},
        }


class CliFailureDiagnosisService:
    """Ask the configured Qwen model whether a CLI error is fixable or needs CUA."""

    def __init__(self, intent_service: IntentService | None = None) -> None:
        self.intent_service = intent_service or IntentService()

    async def diagnose(
        self,
        *,
        action: StandardAction,
        result: ExecutorResult,
        raw_message: str,
    ) -> CliFailureDiagnosis:
        """Classify a CLI failure before switching to desktop CUA control."""
        fallback = self._rule_based_diagnosis(action=action, result=result, raw_message=raw_message)
        if not self.intent_service.settings.dashscope_api_key:
            return fallback

        raw_payload, llm_error = await self.intent_service._request_llm_json(  # noqa: SLF001
            system_prompt=self._diagnosis_prompt(),
            user_payload={
                "raw_user_message": raw_message,
                "capability_id": action.capability_id.value,
                "structured_payload": dict(action.payload),
                "cli_error_code": result.error_code,
                "cli_error_name": cli_error_name(result.error_code),
                "cli_result_summary": result.summary,
                "cli_execution_payload": result.payload,
            },
            max_tokens=512,
            contract_hint=self._contract_hint(),
            allow_repair=True,
            allow_retry=False,
            timeout_seconds=max(1, min(20, int(self.intent_service.settings.qwen_intent_timeout_seconds))),
        )
        if raw_payload is None:
            return CliFailureDiagnosis(
                category=fallback.category,
                should_fallback_to_cua=fallback.should_fallback_to_cua,
                confidence=fallback.confidence,
                reason=f"{fallback.reason}; model diagnosis unavailable: {llm_error or 'unknown'}",
                user_message=fallback.user_message,
                source="rules_after_qwen_failed",
                raw_payload={"llm_error": llm_error or "unknown"},
            )

        normalized = self._normalize_llm_payload(raw_payload)
        if normalized is None:
            return CliFailureDiagnosis(
                category=fallback.category,
                should_fallback_to_cua=fallback.should_fallback_to_cua,
                confidence=fallback.confidence,
                reason=f"{fallback.reason}; model diagnosis returned invalid contract",
                user_message=fallback.user_message,
                source="rules_after_qwen_invalid",
                raw_payload=raw_payload,
            )
        return normalized

    def _rule_based_diagnosis(
        self,
        *,
        action: StandardAction,
        result: ExecutorResult,
        raw_message: str = "",
    ) -> CliFailureDiagnosis:
        code = normalize_error_code(result.error_code)
        if code == UnifiedErrorCode.INVALID_INPUT_OR_RESULT:
            if self._requires_current_ui_context(action=action, raw_message=raw_message):
                return CliFailureDiagnosis(
                    category="requires_ui_context",
                    should_fallback_to_cua=True,
                    confidence=0.80,
                    reason="The command references current Feishu UI state, but structured CLI arguments are incomplete.",
                    user_message="模型判断需要当前飞书界面上下文，准备切换到 CUA 接管。",
                    source="rules",
                )
            return CliFailureDiagnosis(
                category="input_or_syntax_error",
                should_fallback_to_cua=False,
                confidence=0.78,
                reason="CLI returned invalid input/result; likely missing or malformed structured arguments.",
                user_message="模型判断这次更像是输入或参数不完整，请修正目标对象、消息内容或指令格式后重试。",
                source="rules",
            )
        if code == UnifiedErrorCode.PERMISSION_DENIED:
            return CliFailureDiagnosis(
                category="permission_denied",
                should_fallback_to_cua=True,
                confidence=0.72,
                reason="CLI returned permission/authentication error; CUA may still work through the logged-in desktop client.",
                user_message="模型判断 CLI 权限不足，准备切换到 CUA 接管桌面飞书继续尝试。",
                source="rules",
            )
        if code == UnifiedErrorCode.UNSUPPORTED:
            return CliFailureDiagnosis(
                category="cli_unsupported",
                should_fallback_to_cua=True,
                confidence=0.72,
                reason="The requested operation is unsupported by CLI but may be available in the Feishu UI.",
                user_message="模型判断 CLI 不支持该能力，准备切换到 CUA 接管桌面飞书。",
                source="rules",
            )
        if code == UnifiedErrorCode.HANDOFF_REQUIRED:
            return CliFailureDiagnosis(
                category="requires_ui_context",
                should_fallback_to_cua=True,
                confidence=0.82,
                reason="The task explicitly requires current Feishu UI context.",
                user_message="模型判断需要当前飞书界面上下文，准备切换到 CUA 接管。",
                source="rules",
            )
        if code == UnifiedErrorCode.RATE_LIMIT:
            return CliFailureDiagnosis(
                category="runtime_or_network_error",
                should_fallback_to_cua=False,
                confidence=0.70,
                reason="The failure is rate-limit related; CUA fallback is unlikely to fix it immediately.",
                user_message="模型判断当前更像是限流，请稍后重试，暂不接管 CUA。",
                source="rules",
            )
        if code == UnifiedErrorCode.TIMEOUT:
            return CliFailureDiagnosis(
                category="runtime_or_network_error",
                should_fallback_to_cua=True,
                confidence=0.62,
                reason="CLI timed out; desktop CUA may still complete the action through the logged-in client.",
                user_message="模型判断 CLI 执行超时，准备切换到 CUA 接管桌面飞书继续尝试。",
                source="rules",
            )
        return CliFailureDiagnosis(
            category="unknown",
            should_fallback_to_cua=True,
            confidence=0.55,
            reason=f"Uncategorized CLI failure for {action.capability_id.value}; conservative CUA fallback.",
            user_message="模型无法完全确认 CLI 失败原因，准备切换到 CUA 做兜底尝试。",
            source="rules",
        )

    @staticmethod
    def _normalize_llm_payload(payload: dict[str, object]) -> CliFailureDiagnosis | None:
        raw_category = str(payload.get("category", "")).strip().lower()
        categories = {
            "input_or_syntax_error",
            "permission_denied",
            "cli_unsupported",
            "runtime_or_network_error",
            "requires_ui_context",
            "unknown",
        }
        if raw_category not in categories:
            mapped_category = CliFailureDiagnosisService._category_from_failure_reason(
                payload.get("failure_reason")
            )
            if mapped_category is None:
                return None
            raw_category = mapped_category
        raw_should_fallback = payload.get("should_fallback_to_cua")
        if not isinstance(raw_should_fallback, bool):
            raw_should_fallback = payload.get("fallback_to_cua")
        if not isinstance(raw_should_fallback, bool):
            raw_should_fallback = raw_category in {
                "permission_denied",
                "cli_unsupported",
                "requires_ui_context",
                "unknown",
            }
        confidence = CliFailureDiagnosisService._normalize_confidence(payload.get("confidence"))
        reason = str(payload.get("reason", "")).strip()[:500]
        user_message = str(payload.get("user_message", "")).strip()[:300]
        if not reason:
            reason = CliFailureDiagnosisService._default_reason(raw_category, raw_should_fallback)
        if not user_message:
            user_message = CliFailureDiagnosisService._default_user_message(raw_category, raw_should_fallback)
        return CliFailureDiagnosis(
            category=raw_category,  # type: ignore[arg-type]
            should_fallback_to_cua=raw_should_fallback,
            confidence=confidence,
            reason=reason,
            user_message=user_message,
            raw_payload=payload,
        )

    @staticmethod
    def _category_from_failure_reason(value: object) -> DiagnosisCategory | None:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases: dict[str, DiagnosisCategory] = {
            "need_current_ui_context": "requires_ui_context",
            "needs_current_ui_context": "requires_ui_context",
            "requires_current_ui_context": "requires_ui_context",
            "current_ui_context_required": "requires_ui_context",
            "ui_context_required": "requires_ui_context",
            "requires_ui_context": "requires_ui_context",
            "permission": "permission_denied",
            "permission_denied": "permission_denied",
            "auth_required": "permission_denied",
            "cli_unsupported": "cli_unsupported",
            "unsupported": "cli_unsupported",
            "not_supported": "cli_unsupported",
            "input_or_syntax_error": "input_or_syntax_error",
            "invalid_input": "input_or_syntax_error",
            "missing_required_field": "input_or_syntax_error",
            "runtime_or_network_error": "runtime_or_network_error",
            "runtime_error": "runtime_or_network_error",
            "network_error": "runtime_or_network_error",
            "timeout": "runtime_or_network_error",
            "unknown": "unknown",
        }
        return aliases.get(normalized)

    @staticmethod
    def _default_reason(category: str, should_fallback_to_cua: bool) -> str:
        if category == "requires_ui_context":
            return "Model diagnosis indicates the task needs current Feishu UI context."
        if category == "permission_denied":
            return "Model diagnosis indicates a CLI permission or authentication blocker."
        if category == "cli_unsupported":
            return "Model diagnosis indicates the requested operation is unsupported by CLI."
        if category == "runtime_or_network_error":
            return "Model diagnosis indicates a runtime or network failure."
        if category == "input_or_syntax_error":
            return "Model diagnosis indicates missing or malformed structured arguments."
        if should_fallback_to_cua:
            return "Model diagnosis is incomplete, but recommends CUA fallback."
        return "Model diagnosis is incomplete and does not recommend CUA fallback."

    @staticmethod
    def _default_user_message(category: str, should_fallback_to_cua: bool) -> str:
        if category == "requires_ui_context":
            return "模型判断需要当前飞书界面上下文，准备切换到 CUA 接管。"
        if category == "permission_denied":
            return "模型判断 CLI 权限不足，准备切换到 CUA 接管桌面飞书继续尝试。"
        if category == "cli_unsupported":
            return "模型判断 CLI 不支持该能力，准备切换到 CUA 接管桌面飞书。"
        if category == "runtime_or_network_error":
            if should_fallback_to_cua:
                return "模型判断 CLI 运行异常，准备切换到 CUA 接管桌面飞书继续尝试。"
            return "模型判断当前更像是运行或网络问题，暂不接管 CUA。"
        if category == "input_or_syntax_error":
            return "模型判断这次更像是输入或参数不完整，请修正目标对象、消息内容或指令格式后重试。"
        if should_fallback_to_cua:
            return "模型无法完全确认 CLI 失败原因，准备切换到 CUA 做兜底尝试。"
        return "模型诊断后判定暂不接管 CUA。"

    @staticmethod
    def _requires_current_ui_context(*, action: StandardAction, raw_message: str) -> bool:
        payload = action.payload
        payload_text = " ".join(
            str(payload.get(key, ""))
            for key in (
                "failure_reason",
                "resolution_reason",
                "handoff_reason",
                "chat_hint",
                "target_hint",
            )
        )
        combined = f"{raw_message} {payload_text}"
        normalized = combined.lower()
        explicit_markers = (
            "need_current_ui_context",
            "needs_current_ui_context",
            "requires_current_ui_context",
            "current_ui_context_required",
            "ui_context_required",
            "requires_ui_context",
        )
        if any(marker in normalized for marker in explicit_markers):
            return True
        chinese_ui_markers = (
            "点击",
            "消息栏",
            "最上面",
            "最上方",
            "顶部",
            "当前",
            "这个联系人",
            "那个人",
            "刚刚",
            "刚才",
            "选中",
            "界面",
            "窗口",
            "屏幕",
            "列表",
        )
        if any(marker in combined for marker in chinese_ui_markers):
            return True
        english_ui_markers = (
            "click",
            "current ui",
            "current screen",
            "top contact",
            "first contact",
            "selected contact",
            "this contact",
        )
        return any(marker in normalized for marker in english_ui_markers)

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _diagnosis_prompt() -> str:
        return (
            "You diagnose a failed Feishu lark-cli execution before desktop CUA fallback. "
            "Decide whether the failure is caused by user input/CLI argument syntax, real permissions/auth, "
            "CLI capability limits, runtime/network issues, or a need for current Feishu UI context. "
            "Return strict JSON only. If the user can fix the command text or target directly, do not fallback. "
            "If the CLI is blocked by permissions, unsupported API, or needs current UI state, fallback to CUA."
        )

    @staticmethod
    def _contract_hint() -> str:
        return (
            '{"category":"input_or_syntax_error|permission_denied|cli_unsupported|runtime_or_network_error|'
            'requires_ui_context|unknown","should_fallback_to_cua":true|false,'
            '"confidence":0.0-1.0,"reason":"short technical diagnosis",'
            '"user_message":"short Chinese message shown to user"}'
        )
