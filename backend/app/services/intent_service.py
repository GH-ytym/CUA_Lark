"""Intent service backed by MiniMax with deterministic fallback parsing."""

from __future__ import annotations

import json
import re

import httpx

from app.core.config import get_settings
from app.domain.enums import ExecutorType, IntentType
from app.schemas.chat import ParsePreviewResponse


class IntentDecision(ParsePreviewResponse):
    """Intent decision plus action plan and executor hint."""

    action_plan: list[str]
    selected_executor: ExecutorType


class IntentService:
    """Resolve user message intent with LLM-first and rules fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def parse(self, message: str, context_hint: str = "") -> IntentDecision:
        """Parse intent and generate normalized plan."""
        llm_result = await self._parse_with_llm(message=message, context_hint=context_hint)
        if llm_result is not None:
            return llm_result
        return self._parse_with_rules(message)

    async def _parse_with_llm(self, message: str, context_hint: str) -> IntentDecision | None:
        """Call MiniMax in OpenAI-compatible format."""
        if not self.settings.minimax_api_key:
            return None

        prompt = (
            "你是飞书任务规划器。将输入解析为 JSON，字段必须包含："
            "intent_type(message_send|calendar_reschedule|doc_create|sheet_update|unknown),"
            "reason(字符串), action_plan(字符串数组，最多4项)。只输出 JSON，不要其他文字。"
        )
        payload = {
            "model": self.settings.minimax_model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"message": message, "context_hint": context_hint},
                        ensure_ascii=False,
                    ),
                },
            ],
            "max_tokens": 256,
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.minimax_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.minimax_timeout_seconds) as client:
                response = await client.post(self.settings.minimax_chat_url, headers=headers, json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = self._safe_json_loads(content)
                if parsed is None:
                    return None
                intent = self._to_intent_type(str(parsed.get("intent_type", "unknown")))
                reason = str(parsed.get("reason", "parsed by minimax")).strip()[:200]
                plan = self._normalize_plan(parsed.get("action_plan"))
                return IntentDecision(
                    intent_type=intent,
                    reason=reason or "parsed by minimax",
                    action_plan=plan,
                    selected_executor=self._executor_for(intent),
                )
        except Exception:
            return None
        return None

    def _parse_with_rules(self, message: str) -> IntentDecision:
        """Deterministic fallback parser when LLM is unavailable."""
        lowered = message.lower()
        if "会议" in message or "calendar" in lowered or "meeting" in lowered:
            return self._decision(IntentType.CALENDAR_RESCHEDULE, "calendar keyword")
        if "文档" in message or "doc" in lowered:
            return self._decision(IntentType.DOC_CREATE, "doc keyword")
        if "表格" in message or "sheet" in lowered or "单元格" in message:
            return self._decision(IntentType.SHEET_UPDATE, "sheet keyword")
        if "发" in message or "消息" in message or "send" in lowered:
            return self._decision(IntentType.MESSAGE_SEND, "message keyword")
        return self._decision(IntentType.UNKNOWN, "no mvp pattern matched")

    def _decision(
        self,
        intent: IntentType,
        reason: str,
    ) -> IntentDecision:
        plan_templates = {
            IntentType.MESSAGE_SEND: ["定位接收对象", "整理消息正文", "调用 lark-cli 发送并回执"],
            IntentType.CALENDAR_RESCHEDULE: ["定位目标日程", "检查忙闲冲突", "调用 lark-cli 改期并通知参会人"],
            IntentType.DOC_CREATE: ["确认文档主题", "生成初稿结构", "调用 lark-cli 创建并写入内容"],
            IntentType.SHEET_UPDATE: ["定位表格和单元格", "校验更新值", "调用 lark-cli 写入并校验结果"],
            IntentType.UNKNOWN: ["请求用户补充信息", "保持任务为待确认状态"],
        }
        return IntentDecision(
            intent_type=intent,
            reason=reason,
            action_plan=plan_templates[intent],
            selected_executor=self._executor_for(intent),
        )

    @staticmethod
    def _to_intent_type(value: str) -> IntentType:
        normalized = value.strip().lower().replace("-", "_")
        alias = {
            "send_message": IntentType.MESSAGE_SEND,
            "message_send": IntentType.MESSAGE_SEND,
            "reschedule_calendar": IntentType.CALENDAR_RESCHEDULE,
            "calendar_reschedule": IntentType.CALENDAR_RESCHEDULE,
            "create_doc": IntentType.DOC_CREATE,
            "doc_create": IntentType.DOC_CREATE,
            "update_sheet": IntentType.SHEET_UPDATE,
            "sheet_update": IntentType.SHEET_UPDATE,
            "unknown": IntentType.UNKNOWN,
        }
        return alias.get(normalized, IntentType.UNKNOWN)

    @staticmethod
    def _executor_for(intent: IntentType) -> ExecutorType:
        if intent == IntentType.UNKNOWN:
            return ExecutorType.NONE
        return ExecutorType.CLI

    @staticmethod
    def _normalize_plan(raw_plan: object) -> list[str]:
        if isinstance(raw_plan, list):
            normalized = [str(item).strip()[:60] for item in raw_plan if str(item).strip()]
            return normalized[:4] or ["调用 lark-cli 执行并返回结果"]
        if isinstance(raw_plan, str) and raw_plan.strip():
            return [raw_plan.strip()[:60]]
        return ["调用 lark-cli 执行并返回结果"]

    @staticmethod
    def _safe_json_loads(content: str) -> dict[str, object] | None:
        text = content.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        else:
            fenced = re.search(r"```json\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
            if fenced:
                text = fenced.group(1).strip()
            else:
                obj = re.search(r"\{[\s\S]*\}", text)
                if obj:
                    text = obj.group(0).strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
        return None
