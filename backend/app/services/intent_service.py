"""Intent service backed by MiniMax with deterministic fallback parsing."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import Field

from app.core.config import get_settings
from app.domain.enums import ExecutorType, IntentType
from app.schemas.chat import ParsePreviewResponse
from app.services.recipient_resolver import RecipientResolver


class IntentDecision(ParsePreviewResponse):
    """Intent decision plus action plan and executor hint."""

    action_plan: list[str]
    selected_executor: ExecutorType
    parse_source: str = "rules"
    structured_command: dict[str, Any] = Field(default_factory=dict)


class IntentService:
    """Resolve user message intent with LLM-first and rules fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.recipient_resolver = RecipientResolver()

    async def parse(self, message: str, context_hint: str = "") -> IntentDecision:
        """Parse intent and generate normalized plan."""
        lowered = message.lower()
        if self.settings.intent_message_fastpath_enabled and self._looks_like_message_command(message, lowered):
            fast_decision = self._build_message_fastpath_decision(message=message)
            return await self._resolve_message_recipient(decision=fast_decision, message=message)
        local_message_decision = await self._try_message_without_llm(message=message, lowered=lowered)
        if local_message_decision is not None:
            return local_message_decision
        llm_result = await self._parse_with_llm(message=message, context_hint=context_hint)
        if llm_result is not None:
            return llm_result
        if self.settings.minimax_api_key and self.settings.intent_require_llm:
            return IntentDecision(
                intent_type=IntentType.UNKNOWN,
                reason="llm parse failed and rules fallback disabled",
                action_plan=["请用户重述需求或稍后重试"],
                selected_executor=ExecutorType.NONE,
                parse_source="minimax_required",
                structured_command={"intent_type": IntentType.UNKNOWN.value, "payload": {}},
            )
        return await self._parse_with_rules(message)

    async def _parse_with_llm(self, message: str, context_hint: str) -> IntentDecision | None:
        """Call MiniMax with one-shot intent parse and robust fallback handling."""
        if not self.settings.minimax_api_key:
            return None
        intent_raw, llm_error = await self._request_llm_json(
            system_prompt=self._intent_prompt(),
            user_payload={"message": message, "context_hint": context_hint},
            max_tokens=96,
            contract_hint=self._intent_contract_hint(),
            allow_repair=True,
            allow_retry=True,
            timeout_seconds=max(1, int(self.settings.minimax_intent_timeout_seconds)),
        )
        normalized_intent = self._normalize_intent_payload(intent_raw)
        lowered = message.lower()
        if normalized_intent is None:
            if self._looks_like_message_command(message, lowered):
                fallback = self._build_message_fastpath_decision(
                    message=message,
                    parse_source="rules_after_llm",
                    reason=f"llm_failed: {llm_error or 'invalid_json'}",
                )
                return await self._resolve_message_recipient(decision=fallback, message=message)
            return None

        intent = self._to_intent_type(str(normalized_intent.get("intent_type", "unknown")))
        reason = str(normalized_intent.get("reason", "parsed by minimax")).strip()[:200]
        plan = self._normalize_plan(normalized_intent.get("action_plan"))
        entities_raw = normalized_intent.get("entities")
        entities = entities_raw if isinstance(entities_raw, dict) else {}
        if intent == IntentType.UNKNOWN and self._looks_like_message_command(message, lowered):
            intent = IntentType.MESSAGE_SEND
            reason = "口语表达命中消息发送语义"
            entities = self._extract_message_entities(message)
            plan = self._normalize_plan(["定位接收对象", "整理消息正文", "发送消息"])

        decision = IntentDecision(
            intent_type=intent,
            reason=reason or "parsed by minimax",
            action_plan=plan,
            selected_executor=self._executor_for(intent),
            parse_source="minimax",
            structured_command=self._build_structured_command(intent=intent, message=message, entities=entities),
        )
        return await self._resolve_message_recipient(decision=decision, message=message)

    async def _request_llm_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int,
        contract_hint: str,
        allow_repair: bool,
        allow_retry: bool,
        timeout_seconds: int,
    ) -> tuple[dict[str, object] | None, str | None]:
        content, chat_error = await self._chat_completion(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        if chat_error:
            return None, chat_error
        parsed = self._safe_json_loads(content)
        if parsed is not None:
            return parsed, None

        if not allow_repair:
            return None, "invalid_json_initial"
        # One repair pass: ask model to rewrite prior output into strict JSON only.
        repair_prompt = (
            "你是 JSON 修复器。只输出一个 JSON 对象，不要 markdown、不要解释。"
            f"目标契约：{contract_hint}"
        )
        repaired, repair_error = await self._chat_completion(
            system_prompt=repair_prompt,
            user_payload={"bad_output": content, "original_input": user_payload},
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        if repair_error:
            return None, f"repair_{repair_error}"
        repaired_json = self._safe_json_loads(repaired)
        if repaired_json is not None:
            return repaired_json, None

        if not allow_retry:
            return None, "invalid_json_repair"
        # Retry once with original prompt to smooth out transient model drift.
        retry_content, retry_error = await self._chat_completion(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        if retry_error:
            return None, f"retry_{retry_error}"
        parsed_retry = self._safe_json_loads(retry_content)
        if parsed_retry is not None:
            return parsed_retry, None
        return None, "invalid_json_retry"

    async def _chat_completion(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> tuple[str, str | None]:
        payload = {
            "model": self.settings.minimax_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.minimax_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=max(1, timeout_seconds)) as client:
                response = await client.post(self.settings.minimax_chat_url, headers=headers, json=payload)
                response.raise_for_status()
                content = str(response.json()["choices"][0]["message"]["content"])
                return content, None
        except httpx.TimeoutException:
            return "", "timeout"
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return "", f"http_{status}"
        except httpx.HTTPError:
            return "", "network_error"
        except (KeyError, TypeError, ValueError):
            return "", "response_schema_error"
        except Exception:
            return "", "unknown_error"

    def _normalize_intent_payload(self, data: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(data, dict):
            return None
        action = str(data.get("action", "")).strip().lower()
        target = str(data.get("target", "")).strip()
        msg = str(data.get("message", "")).strip()
        if action in {"greeting", "message", "send_message"}:
            return {
                "intent_type": "message_send",
                "reason": "用户希望发送消息",
                "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                "entities": {"chat_hint": target, "chat_id": "", "user_id": "", "message_text": msg},
            }

        intent = self._to_intent_type(str(data.get("intent_type", "unknown")))
        entities_raw = data.get("entities")
        entities = entities_raw if isinstance(entities_raw, dict) else {}
        if intent == IntentType.MESSAGE_SEND:
            entities = self._normalize_message_entities(entities) or {}

        return {
            "intent_type": intent.value,
            "reason": str(data.get("reason", "parsed by minimax")).strip()[:200] or "parsed by minimax",
            "action_plan": self._normalize_plan(data.get("action_plan")),
            "entities": entities,
        }

    @staticmethod
    def _normalize_message_entities(data: dict[str, object] | None) -> dict[str, str] | None:
        if not isinstance(data, dict):
            return None
        source = data
        nested = data.get("entities")
        if isinstance(nested, dict):
            source = nested
        chat_hint = str(source.get("chat_hint", source.get("target", source.get("recipient", "")))).strip()
        chat_id = str(source.get("chat_id", "")).strip()
        user_id = str(source.get("user_id", "")).strip()
        message_text = str(source.get("message_text", source.get("text", source.get("message", "")))).strip()
        if not (chat_hint or chat_id or user_id or message_text):
            return None
        return {
            "chat_hint": chat_hint,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_text": message_text,
        }

    @staticmethod
    def _needs_message_enrichment(entities: dict[str, Any]) -> bool:
        chat_hint = str(entities.get("chat_hint", "")).strip()
        chat_id = str(entities.get("chat_id", "")).strip()
        user_id = str(entities.get("user_id", "")).strip()
        message_text = str(entities.get("message_text", entities.get("text", ""))).strip()
        has_target = bool(chat_hint or chat_id or user_id)
        has_text = bool(message_text)
        return not (has_target and has_text)

    @staticmethod
    def _intent_prompt() -> str:
        return (
            "你是飞书意图分类器。只输出一个 JSON 对象，不要 markdown、解释、思考过程。"
            "固定字段：intent_type, reason, action_plan, entities。"
            "intent_type 只能是 message_send|calendar_reschedule|doc_create|sheet_update|unknown。"
            "口语句式“跟X说...”“给X说...”“发消息给X...”判定为 message_send。"
            "message_send 时 entities 至少含 chat_hint 与 message_text（未知则空字符串）。"
            "禁止输出字段 action/target/message。"
        )

    @staticmethod
    def _message_entity_prompt() -> str:
        return (
            "你是飞书消息实体提取器。只输出一个 JSON 对象，不要 markdown、解释、思考过程。"
            "固定字段：chat_hint, chat_id, user_id, message_text。"
            "chat_id/user_id 无法确定时给空字符串；不要杜撰 ID。"
            "对于“跟梅家济说hello”应输出 chat_hint=梅家济, message_text=hello。"
        )

    @staticmethod
    def _intent_contract_hint() -> str:
        return (
            '{"intent_type":"message_send|calendar_reschedule|doc_create|sheet_update|unknown",'
            '"reason":"...",'
            '"action_plan":["..."],'
            '"entities":{"chat_hint":"","chat_id":"","user_id":"","message_text":""}}'
        )

    @staticmethod
    def _message_entity_contract_hint() -> str:
        return '{"chat_hint":"","chat_id":"","user_id":"","message_text":""}'

    async def _parse_with_rules(self, message: str) -> IntentDecision:
        """Deterministic fallback parser when LLM is unavailable."""
        lowered = message.lower()
        if "会议" in message or "calendar" in lowered or "meeting" in lowered:
            return await self._resolve_message_recipient(
                decision=self._decision(IntentType.CALENDAR_RESCHEDULE, "calendar keyword", message=message),
                message=message,
            )
        if "文档" in message or "doc" in lowered:
            return await self._resolve_message_recipient(
                decision=self._decision(IntentType.DOC_CREATE, "doc keyword", message=message),
                message=message,
            )
        if "表格" in message or "sheet" in lowered or "单元格" in message:
            return await self._resolve_message_recipient(
                decision=self._decision(IntentType.SHEET_UPDATE, "sheet keyword", message=message),
                message=message,
            )
        if "发" in message or "消息" in message or "send" in lowered:
            return await self._resolve_message_recipient(
                decision=self._decision(IntentType.MESSAGE_SEND, "message keyword", message=message),
                message=message,
            )
        return await self._resolve_message_recipient(
            decision=self._decision(IntentType.UNKNOWN, "no mvp pattern matched", message=message),
            message=message,
        )

    def _decision(
        self,
        intent: IntentType,
        reason: str,
        message: str = "",
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
            parse_source="rules",
            structured_command=self._build_structured_command(intent=intent, message=message, entities={}),
        )

    def _build_message_fastpath_decision(
        self,
        message: str,
        parse_source: str = "rules_fastpath",
        reason: str = "消息发送快路径命中",
    ) -> IntentDecision:
        entities = self._extract_message_entities(message)
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason=reason,
            action_plan=["定位接收对象", "整理消息正文", "发送消息"],
            selected_executor=ExecutorType.CLI,
            parse_source=parse_source,
            structured_command=self._build_structured_command(
                intent=IntentType.MESSAGE_SEND,
                message=message,
                entities={
                    "chat_hint": entities.get("chat_hint", ""),
                    "chat_id": entities.get("chat_id", ""),
                    "user_id": entities.get("user_id", ""),
                    "message_text": entities.get("text", ""),
                },
            ),
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

    def _build_structured_command(
        self,
        intent: IntentType,
        message: str,
        entities: dict[str, Any],
    ) -> dict[str, Any]:
        if intent != IntentType.MESSAGE_SEND:
            return {"intent_type": intent.value, "payload": {}}
        fallback_entities = self._extract_message_entities(message)
        merged_entities = {
            "chat_hint": str(entities.get("chat_hint", fallback_entities.get("chat_hint", ""))).strip(),
            "chat_id": str(entities.get("chat_id", fallback_entities.get("chat_id", ""))).strip(),
            "user_id": str(entities.get("user_id", fallback_entities.get("user_id", ""))).strip(),
            "text": str(entities.get("message_text", fallback_entities.get("text", ""))).strip(),
        }
        return {"intent_type": intent.value, "payload": merged_entities}

    @staticmethod
    def _extract_message_entities(message: str) -> dict[str, str]:
        recipient = ""
        content = ""
        patterns = [
            r"(?:给|跟|对)(?P<target>[^\s：:，。,]{1,60})(?:发送|发|说|讲|回复)[:：]?(?P<body>.+)",
            r"(?:发|发送)消息给(?P<target>[^\s：:，。,]{1,60})[:：]?(?P<body>.+)",
            r"在(?P<target>[^\s：:，。,]{1,60})里?(?:发送|发|说|讲)[:：]?(?P<body>.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                recipient = match.group("target").strip().removesuffix("里")
                content = match.group("body").strip("：:，。 ").strip()
                break
        if not content:
            quote = re.search(r"[“\"](?P<body>[^”\"]+)[”\"]", message)
            if quote:
                content = quote.group("body").strip()
        if not content:
            simple = re.search(r"(发送|发)(?P<body>.+)", message)
            if simple:
                content = simple.group("body").strip("：:，。 ").strip()
        if not content:
            content = message.strip()[:120]
        return {"chat_hint": recipient, "chat_id": "", "user_id": "", "text": content}

    @staticmethod
    def _looks_like_message_command(message: str, lowered: str) -> bool:
        if re.search(r"(给|跟|在).{1,40}(发|发送|说)", message):
            return True
        if re.search(r"(发|发送)消息给", message):
            return True
        return "send" in lowered or "消息" in message

    async def _resolve_message_recipient(self, decision: IntentDecision, message: str) -> IntentDecision:
        if decision.intent_type != IntentType.MESSAGE_SEND:
            return decision
        structured = decision.structured_command if isinstance(decision.structured_command, dict) else {}
        payload = structured.get("payload") if isinstance(structured.get("payload"), dict) else {}
        resolved_payload = await self.recipient_resolver.resolve(message=message, payload=dict(payload))
        if resolved_payload == payload:
            return decision
        updated_structured = dict(structured)
        updated_structured["payload"] = resolved_payload
        return decision.model_copy(update={"structured_command": updated_structured})

    async def _try_message_without_llm(self, message: str, lowered: str) -> IntentDecision | None:
        if not self._looks_like_message_command(message, lowered):
            return None
        decision = self._build_message_fastpath_decision(
            message=message,
            parse_source="rules_resolve_first",
            reason="消息发送本地解析命中",
        )
        resolved = await self._resolve_message_recipient(decision=decision, message=message)
        payload = resolved.structured_command.get("payload", {})
        if not isinstance(payload, dict):
            return None
        if payload.get("chat_id") or payload.get("user_id"):
            return resolved
        resolution_status = str(payload.get("resolution_status", "")).strip().lower()
        if resolution_status == "needs_confirmation" and payload.get("resolution_candidates"):
            return resolved
        return None
