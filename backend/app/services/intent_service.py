"""Intent service backed by MiniMax with deterministic fallback parsing."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import Field

from app.core.config import get_settings
from app.domain.enums import CapabilityId, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.schemas.chat import ParsePreviewResponse
from app.services.recipient_resolver import RecipientResolver


class IntentDecision(ParsePreviewResponse):
    """Intent decision plus action plan and executor hint."""

    action_plan: list[str]
    selected_executor: ExecutorType
    parse_source: str = "rules"
    standard_action: StandardAction = Field(default_factory=StandardAction)
    structured_command: dict[str, Any] = Field(default_factory=dict)


class IntentService:
    """Resolve user message intent with LLM-first and rules fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.recipient_resolver = RecipientResolver()

    async def parse(self, message: str, context_hint: str = "") -> IntentDecision:
        """Parse intent and generate normalized plan."""
        lowered = message.lower()
        if self.settings.intent_message_fastpath_enabled and self._looks_like_message_send_command(message, lowered):
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
                standard_action=self._build_standard_action(intent=IntentType.UNKNOWN, payload={}),
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
            if self._looks_like_message_send_command(message, lowered):
                fallback = self._build_message_fastpath_decision(
                    message=message,
                    parse_source="rules_after_llm",
                    reason=f"llm_failed: {llm_error or 'invalid_json'}",
                )
                return await self._resolve_message_recipient(decision=fallback, message=message)
            return None

        capability_id = self._to_capability_id(str(normalized_intent.get("capability_id", "")))
        intent = self._to_intent_type(str(normalized_intent.get("intent_type", "unknown")))
        if capability_id != CapabilityId.UNKNOWN:
            intent = self._intent_for_capability(capability_id)
        reason = str(normalized_intent.get("reason", "parsed by minimax")).strip()[:200]
        plan = self._normalize_plan(normalized_intent.get("action_plan"))
        entities_raw = normalized_intent.get("entities")
        entities = entities_raw if isinstance(entities_raw, dict) else {}
        if not entities and isinstance(normalized_intent.get("payload"), dict):
            entities = dict(normalized_intent["payload"])
        if intent == IntentType.UNKNOWN and self._looks_like_message_send_command(message, lowered):
            intent = IntentType.MESSAGE_SEND
            reason = "口语表达命中消息发送语义"
            entities = self._extract_message_entities(message)
            plan = self._normalize_plan(["定位接收对象", "整理消息正文", "发送消息"])
            capability_id = CapabilityId.IM_MESSAGE_SEND

        structured_command = self._build_structured_command(
            intent=intent,
            message=message,
            entities=entities,
            capability_id=capability_id,
        )
        payload = self._payload_from_structured_command(structured_command)
        if capability_id == CapabilityId.UNKNOWN:
            capability_id = self._capability_for_intent(intent)
        decision = IntentDecision(
            intent_type=intent,
            reason=reason or "parsed by minimax",
            action_plan=plan,
            selected_executor=self._executor_for(intent),
            parse_source="minimax",
            standard_action=self._build_standard_action(
                intent=intent,
                payload=payload,
                capability_id=capability_id,
            ),
            structured_command=structured_command,
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
        capability_id = self._to_capability_id(str(data.get("capability_id", "")))
        if capability_id != CapabilityId.UNKNOWN:
            payload_raw = data.get("payload", data.get("entities", {}))
            payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
            if capability_id == CapabilityId.IM_MESSAGE_SEND:
                payload = self._normalize_message_entities(payload) or payload
            intent = self._intent_for_capability(capability_id)
            return {
                "intent_type": intent.value,
                "capability_id": capability_id.value,
                "reason": str(data.get("reason", "parsed by minimax")).strip()[:200] or "parsed by minimax",
                "action_plan": self._normalize_plan(data.get("action_plan")),
                "entities": payload,
            }
        action = str(data.get("action", "")).strip().lower()
        target = str(data.get("target", "")).strip()
        msg = str(data.get("message", "")).strip()
        if action in {"greeting", "message", "send_message"}:
            return {
                "intent_type": "message_send",
                "capability_id": CapabilityId.IM_MESSAGE_SEND.value,
                "reason": "用户希望发送消息",
                "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                "entities": {"chat_hint": target, "chat_id": "", "user_id": "", "text": msg},
            }

        intent = self._to_intent_type(str(data.get("intent_type", "unknown")))
        entities_raw = data.get("entities")
        entities = entities_raw if isinstance(entities_raw, dict) else {}
        if intent == IntentType.MESSAGE_SEND:
            entities = self._normalize_message_entities(entities) or {}

        return {
            "intent_type": intent.value,
            "capability_id": self._capability_for_intent(intent).value,
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
            "text": message_text,
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
            "你是飞书任务解析器。只输出一个 JSON 对象，不要 markdown、解释、思考过程。"
            "固定字段：capability_id, reason, action_plan, payload。"
            "capability_id 必须是：im.message_send|im.messages_reply|im.messages_search|"
            "im.chat_messages_list|im.chat_search|im.chat_create|calendar.create|calendar.reschedule|"
            "calendar.agenda|calendar.freebusy|docs.create|docs.update|docs.search|sheets.update|"
            "sheets.read|contact.search|task.create|mail.send|base.record_create|unknown。"
            "payload 放任务参数；不确定的参数给空字符串，不要杜撰 ID。"
            "例如发消息 payload 至少含 chat_hint/chat_id/user_id/text；文档创建含 title/content；"
            "日程创建含 title/start_time/end_time/attendees；搜索含 query。"
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
            '{"capability_id":"im.message_send|docs.create|calendar.create|unknown",'
            '"reason":"...",'
            '"action_plan":["..."],'
            '"payload":{"query":"","title":"","chat_hint":"","text":""}}'
        )

    @staticmethod
    def _message_entity_contract_hint() -> str:
        return '{"chat_hint":"","chat_id":"","user_id":"","message_text":""}'

    async def _parse_with_rules(self, message: str) -> IntentDecision:
        """Deterministic fallback parser when LLM is unavailable."""
        lowered = message.lower()
        capability_id = self._classify_capability(message=message, lowered=lowered)
        if capability_id == CapabilityId.IM_MESSAGE_SEND:
            return await self._resolve_message_recipient(
                decision=self._decision(
                    intent=IntentType.MESSAGE_SEND,
                    reason="message send keyword",
                    message=message,
                    capability_id=capability_id,
                ),
                message=message,
            )
        return self._decision(
            intent=self._intent_for_capability(capability_id),
            reason=f"{capability_id.value} keyword" if capability_id != CapabilityId.UNKNOWN else "no capability pattern matched",
            message=message,
            capability_id=capability_id,
        )

    def _classify_capability(self, message: str, lowered: str) -> CapabilityId:
        if self._has_any(message, ("搜索", "查找", "查询")) and "消息" in message:
            return CapabilityId.IM_MESSAGES_SEARCH
        if self._has_any(message, ("回复", "回一条", "回消息")):
            return CapabilityId.IM_MESSAGES_REPLY
        if self._has_any(message, ("列出", "查看", "拉取")) and self._has_any(message, ("聊天记录", "群消息", "消息列表")):
            return CapabilityId.IM_CHAT_MESSAGES_LIST
        if self._has_any(message, ("搜索群", "查找群", "找群")) or "chat search" in lowered:
            return CapabilityId.IM_CHAT_SEARCH
        if self._has_any(message, ("建群", "创建群", "拉群")):
            return CapabilityId.IM_CHAT_CREATE
        if self._looks_like_message_send_command(message, lowered):
            return CapabilityId.IM_MESSAGE_SEND
        if self._has_any(message, ("忙闲", "空闲", "freebusy")) or "freebusy" in lowered:
            return CapabilityId.CALENDAR_FREEBUSY
        if self._has_any(message, ("日程安排", "今天日程", "明天日程", "agenda")) or "agenda" in lowered:
            return CapabilityId.CALENDAR_AGENDA
        if self._has_any(message, ("改期", "改到", "延期", "提前")) and self._has_any(message, ("会议", "日程", "calendar")):
            return CapabilityId.CALENDAR_RESCHEDULE
        if self._has_any(message, ("创建日程", "新建日程", "安排会议", "创建会议")) or "calendar create" in lowered:
            return CapabilityId.CALENDAR_CREATE
        if self._has_any(message, ("搜索文档", "查找文档", "找文档")) or "doc search" in lowered:
            return CapabilityId.DOC_SEARCH
        if self._has_any(message, ("更新文档", "修改文档", "编辑文档")) or "doc update" in lowered:
            return CapabilityId.DOC_UPDATE
        if self._has_any(message, ("创建文档", "新建文档")) or "doc create" in lowered:
            return CapabilityId.DOC_CREATE
        if (
            self._has_any(message, ("读取表格", "查看表格", "读表格"))
            or ("表格" in message and self._has_any(message, ("读取", "查看", "读")))
            or "sheet read" in lowered
        ):
            return CapabilityId.SHEET_READ
        if (
            self._has_any(message, ("更新表格", "写入表格", "修改表格", "单元格"))
            or ("表格" in message and self._has_any(message, ("更新", "写入", "修改")))
            or "sheet update" in lowered
        ):
            return CapabilityId.SHEET_UPDATE
        if self._has_any(message, ("搜索联系人", "查找联系人", "找人", "查通讯录")):
            return CapabilityId.CONTACT_SEARCH
        if self._has_any(message, ("创建任务", "新建任务", "建待办", "创建待办")):
            return CapabilityId.TASK_CREATE
        if self._has_any(message, ("发邮件", "发送邮件", "写邮件")):
            return CapabilityId.MAIL_SEND
        if self._has_any(message, ("新增记录", "添加记录", "写入多维表格", "base")):
            return CapabilityId.BASE_RECORD_CREATE
        return CapabilityId.UNKNOWN

    @staticmethod
    def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in keywords)

    def _payload_for_capability(self, capability_id: CapabilityId, message: str) -> dict[str, object]:
        if capability_id == CapabilityId.IM_MESSAGE_SEND:
            return self._extract_message_entities(message)
        if capability_id == CapabilityId.IM_MESSAGES_REPLY:
            return {"message_hint": self._extract_after_colon(message), "text": self._extract_after_colon(message)}
        if capability_id in {CapabilityId.IM_MESSAGES_SEARCH, CapabilityId.IM_CHAT_SEARCH, CapabilityId.DOC_SEARCH, CapabilityId.CONTACT_SEARCH}:
            return {"query": self._extract_query(message)}
        if capability_id == CapabilityId.IM_CHAT_MESSAGES_LIST:
            return {"chat_hint": self._extract_chat_hint(message), "limit": 20}
        if capability_id == CapabilityId.IM_CHAT_CREATE:
            return {"name": self._extract_title(message), "member_hints": self._extract_member_hints(message)}
        if capability_id in {CapabilityId.CALENDAR_CREATE, CapabilityId.CALENDAR_RESCHEDULE}:
            return {
                "title": self._extract_title(message),
                "event_hint": self._extract_event_hint(message),
                "start_time": self._extract_time_hint(message, "start"),
                "end_time": self._extract_time_hint(message, "end"),
                "target_time": self._extract_time_hint(message, "target"),
                "attendees": self._extract_member_hints(message),
            }
        if capability_id in {CapabilityId.CALENDAR_AGENDA, CapabilityId.CALENDAR_FREEBUSY}:
            return {"time_range": self._extract_time_range(message), "user_hints": self._extract_member_hints(message)}
        if capability_id in {CapabilityId.DOC_CREATE, CapabilityId.DOC_UPDATE}:
            return {"title": self._extract_title(message), "content": self._extract_after_colon(message), "doc_hint": self._extract_doc_hint(message)}
        if capability_id in {CapabilityId.SHEET_UPDATE, CapabilityId.SHEET_READ}:
            return {
                "sheet_hint": self._extract_sheet_hint(message),
                "cell": self._extract_cell_hint(message),
                "value": self._extract_after_value_marker(message),
            }
        if capability_id == CapabilityId.TASK_CREATE:
            return {"title": self._extract_title(message), "assignee_hints": self._extract_member_hints(message)}
        if capability_id == CapabilityId.MAIL_SEND:
            return {"to_hints": self._extract_member_hints(message), "subject": self._extract_title(message), "body": self._extract_after_colon(message)}
        if capability_id == CapabilityId.BASE_RECORD_CREATE:
            return {"base_hint": self._extract_sheet_hint(message), "record": {"raw": message}}
        return {}

    @staticmethod
    def _extract_after_colon(message: str) -> str:
        parts = re.split(r"[:：]", message, maxsplit=1)
        return parts[1].strip() if len(parts) == 2 else ""

    @staticmethod
    def _extract_query(message: str) -> str:
        about = re.search(r"(?:关于|包含)(?P<query>[\w\u4e00-\u9fff]+?)(?:的|消息|文档|$)", message)
        if about:
            return about.group("query").strip()
        match = re.search(r"(?:搜索|查找|查询|找)(?P<query>[\w\u4e00-\u9fff]+)", message)
        return match.group("query").strip() if match else message.strip()[:80]

    @staticmethod
    def _extract_title(message: str) -> str:
        match = re.search(r"(?:标题叫|标题为|叫|名为|主题是|主题为)(?P<title>[\w\u4e00-\u9fff -]{1,80})", message)
        if match:
            return match.group("title").strip()
        colon_content = IntentService._extract_after_colon(message)
        return colon_content[:80] if colon_content else message.strip()[:80]

    @staticmethod
    def _extract_chat_hint(message: str) -> str:
        match = re.search(r"(?:在|搜索|查看|列出)(?P<hint>[\w\u4e00-\u9fff -]{1,40})(?:里|群|的)", message)
        return match.group("hint").strip() if match else ""

    @staticmethod
    def _extract_event_hint(message: str) -> str:
        match = re.search(r"(?P<hint>[\w\u4e00-\u9fff -]{1,40})(?:会议|日程)", message)
        return match.group("hint").strip() if match else ""

    @staticmethod
    def _extract_doc_hint(message: str) -> str:
        match = re.search(r"(?:文档|doc)(?P<hint>[\w\u4e00-\u9fff -]{1,40})", message, flags=re.IGNORECASE)
        return match.group("hint").strip() if match else ""

    @staticmethod
    def _extract_sheet_hint(message: str) -> str:
        match = re.search(r"(?:表格|sheet|多维表格|base)(?P<hint>[\w\u4e00-\u9fff -]{0,40})", message, flags=re.IGNORECASE)
        return match.group("hint").strip() if match else ""

    @staticmethod
    def _extract_cell_hint(message: str) -> str:
        match = re.search(r"[A-Z]{1,3}[0-9]{1,7}", message, flags=re.IGNORECASE)
        return match.group(0).upper() if match else ""

    @staticmethod
    def _extract_after_value_marker(message: str) -> str:
        match = re.search(r"(?:为|成|写入|更新为)(?P<value>[^，。；;]+)", message)
        return match.group("value").strip() if match else IntentService._extract_after_colon(message)

    @staticmethod
    def _extract_time_hint(message: str, _: str) -> str:
        match = re.search(r"(今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])?[^，。；;]*(?:[0-2]?[0-9][:：点][0-5]?[0-9]?|上午|下午|晚上)", message)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _extract_time_range(message: str) -> str:
        match = re.search(r"(今天|明天|后天|本周|下周|上午|下午|晚上)", message)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _extract_member_hints(message: str) -> list[str]:
        match = re.search(r"(?:给|邀请|成员|收件人|负责人)(?P<names>[\w\u4e00-\u9fff 、,，]{1,80})", message)
        if not match:
            return []
        return [item.strip() for item in re.split(r"[、,，\s]+", match.group("names")) if item.strip()]

    def _decision(
        self,
        intent: IntentType,
        reason: str,
        message: str = "",
        capability_id: CapabilityId | None = None,
    ) -> IntentDecision:
        resolved_capability = capability_id or self._capability_for_intent(intent)
        plan_templates = {
            IntentType.MESSAGE_SEND: ["定位接收对象", "整理消息正文", "调用 lark-cli 发送并回执"],
            IntentType.CALENDAR_RESCHEDULE: ["定位目标日程", "检查忙闲冲突", "调用 lark-cli 改期并通知参会人"],
            IntentType.DOC_CREATE: ["确认文档主题", "生成初稿结构", "调用 lark-cli 创建并写入内容"],
            IntentType.SHEET_UPDATE: ["定位表格和单元格", "校验更新值", "调用 lark-cli 写入并校验结果"],
            IntentType.UNKNOWN: ["请求用户补充信息", "保持任务为待确认状态"],
        }
        structured_command = self._build_structured_command(
            intent=intent,
            message=message,
            entities=self._payload_for_capability(resolved_capability, message),
            capability_id=resolved_capability,
        )
        payload = self._payload_from_structured_command(structured_command)
        return IntentDecision(
            intent_type=intent,
            reason=reason,
            action_plan=plan_templates[intent],
            selected_executor=self._executor_for(intent),
            parse_source="rules",
            standard_action=self._build_standard_action(
                intent=intent,
                payload=payload,
                capability_id=resolved_capability,
            ),
            structured_command=structured_command,
        )

    def _build_message_fastpath_decision(
        self,
        message: str,
        parse_source: str = "rules_fastpath",
        reason: str = "消息发送快路径命中",
    ) -> IntentDecision:
        entities = self._extract_message_entities(message)
        structured_command = self._build_structured_command(
            intent=IntentType.MESSAGE_SEND,
            message=message,
            entities={
                "chat_hint": entities.get("chat_hint", ""),
                "chat_id": entities.get("chat_id", ""),
                "user_id": entities.get("user_id", ""),
                "message_text": entities.get("text", ""),
            },
            capability_id=CapabilityId.IM_MESSAGE_SEND,
        )
        payload = self._payload_from_structured_command(structured_command)
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason=reason,
            action_plan=["定位接收对象", "整理消息正文", "发送消息"],
            selected_executor=ExecutorType.CLI,
            parse_source=parse_source,
            standard_action=self._build_standard_action(
                intent=IntentType.MESSAGE_SEND,
                payload=payload,
                capability_id=CapabilityId.IM_MESSAGE_SEND,
            ),
            structured_command=structured_command,
        )

    @staticmethod
    def _to_intent_type(value: str) -> IntentType:
        normalized = value.strip().lower().replace("-", "_")
        alias = {
            "send_message": IntentType.MESSAGE_SEND,
            "message_send": IntentType.MESSAGE_SEND,
            "message_reply": IntentType.MESSAGE_SEND,
            "messages_reply": IntentType.MESSAGE_SEND,
            "message_search": IntentType.MESSAGE_SEND,
            "messages_search": IntentType.MESSAGE_SEND,
            "chat_search": IntentType.MESSAGE_SEND,
            "chat_create": IntentType.MESSAGE_SEND,
            "reschedule_calendar": IntentType.CALENDAR_RESCHEDULE,
            "calendar_reschedule": IntentType.CALENDAR_RESCHEDULE,
            "calendar_create": IntentType.CALENDAR_RESCHEDULE,
            "calendar_agenda": IntentType.CALENDAR_RESCHEDULE,
            "calendar_freebusy": IntentType.CALENDAR_RESCHEDULE,
            "create_doc": IntentType.DOC_CREATE,
            "doc_create": IntentType.DOC_CREATE,
            "docs_create": IntentType.DOC_CREATE,
            "docs_update": IntentType.DOC_CREATE,
            "docs_search": IntentType.DOC_CREATE,
            "update_sheet": IntentType.SHEET_UPDATE,
            "sheet_update": IntentType.SHEET_UPDATE,
            "sheets_update": IntentType.SHEET_UPDATE,
            "sheets_read": IntentType.SHEET_UPDATE,
            "unknown": IntentType.UNKNOWN,
        }
        return alias.get(normalized, IntentType.UNKNOWN)

    @staticmethod
    def _to_capability_id(value: str) -> CapabilityId:
        normalized = value.strip().lower().replace("_", ".").replace("-", ".")
        alias = {
            item.value: item for item in CapabilityId
        }
        alias.update({
            "message.send": CapabilityId.IM_MESSAGE_SEND,
            "send.message": CapabilityId.IM_MESSAGE_SEND,
            "message.reply": CapabilityId.IM_MESSAGES_REPLY,
            "message.search": CapabilityId.IM_MESSAGES_SEARCH,
            "chat.messages.list": CapabilityId.IM_CHAT_MESSAGES_LIST,
            "chat.search": CapabilityId.IM_CHAT_SEARCH,
            "chat.create": CapabilityId.IM_CHAT_CREATE,
            "calendar.reschedule": CapabilityId.CALENDAR_RESCHEDULE,
            "calendar.event.reschedule": CapabilityId.CALENDAR_RESCHEDULE,
            "calendar.event.create": CapabilityId.CALENDAR_CREATE,
            "doc.create": CapabilityId.DOC_CREATE,
            "doc.update": CapabilityId.DOC_UPDATE,
            "doc.search": CapabilityId.DOC_SEARCH,
            "sheet.update": CapabilityId.SHEET_UPDATE,
            "sheet.read": CapabilityId.SHEET_READ,
            "mail.send": CapabilityId.MAIL_SEND,
            "task.create": CapabilityId.TASK_CREATE,
        })
        return alias.get(normalized, CapabilityId.UNKNOWN)

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
        capability_id: CapabilityId | None = None,
    ) -> dict[str, Any]:
        resolved_capability = capability_id or self._capability_for_intent(intent)
        if resolved_capability != CapabilityId.IM_MESSAGE_SEND:
            return {
                "intent_type": intent.value,
                "capability_id": resolved_capability.value,
                "payload": dict(entities),
            }
        fallback_entities = self._extract_message_entities(message)
        merged_entities = {
            "chat_hint": str(entities.get("chat_hint", fallback_entities.get("chat_hint", ""))).strip(),
            "chat_id": str(entities.get("chat_id", fallback_entities.get("chat_id", ""))).strip(),
            "user_id": str(entities.get("user_id", fallback_entities.get("user_id", ""))).strip(),
            "text": str(
                entities.get(
                    "text",
                    entities.get("message_text", fallback_entities.get("text", "")),
                )
            ).strip(),
        }
        return {
            "intent_type": intent.value,
            "capability_id": resolved_capability.value,
            "payload": merged_entities,
        }

    @staticmethod
    def _payload_from_structured_command(structured_command: dict[str, Any]) -> dict[str, object]:
        payload = structured_command.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _capability_for_intent(intent: IntentType) -> CapabilityId:
        mapping = {
            IntentType.MESSAGE_SEND: CapabilityId.IM_MESSAGE_SEND,
            IntentType.CALENDAR_RESCHEDULE: CapabilityId.CALENDAR_RESCHEDULE,
            IntentType.DOC_CREATE: CapabilityId.DOC_CREATE,
            IntentType.SHEET_UPDATE: CapabilityId.SHEET_UPDATE,
            IntentType.UNKNOWN: CapabilityId.UNKNOWN,
        }
        return mapping.get(intent, CapabilityId.UNKNOWN)

    @staticmethod
    def _intent_for_capability(capability_id: CapabilityId) -> IntentType:
        if capability_id in {
            CapabilityId.IM_MESSAGE_SEND,
            CapabilityId.IM_MESSAGES_REPLY,
            CapabilityId.IM_MESSAGES_SEARCH,
            CapabilityId.IM_CHAT_MESSAGES_LIST,
            CapabilityId.IM_CHAT_SEARCH,
            CapabilityId.IM_CHAT_CREATE,
            CapabilityId.CONTACT_SEARCH,
            CapabilityId.TASK_CREATE,
            CapabilityId.MAIL_SEND,
            CapabilityId.BASE_RECORD_CREATE,
        }:
            return IntentType.MESSAGE_SEND
        if capability_id in {
            CapabilityId.CALENDAR_CREATE,
            CapabilityId.CALENDAR_RESCHEDULE,
            CapabilityId.CALENDAR_AGENDA,
            CapabilityId.CALENDAR_FREEBUSY,
        }:
            return IntentType.CALENDAR_RESCHEDULE
        if capability_id in {CapabilityId.DOC_CREATE, CapabilityId.DOC_UPDATE, CapabilityId.DOC_SEARCH}:
            return IntentType.DOC_CREATE
        if capability_id in {CapabilityId.SHEET_UPDATE, CapabilityId.SHEET_READ}:
            return IntentType.SHEET_UPDATE
        return IntentType.UNKNOWN

    def _build_standard_action(
        self,
        intent: IntentType,
        payload: dict[str, object],
        capability_id: CapabilityId | None = None,
    ) -> StandardAction:
        return StandardAction(
            capability_id=capability_id or self._capability_for_intent(intent),
            payload=payload,
            executor_hint=self._executor_for(intent),
            intent_type=intent,
        )

    @staticmethod
    def _extract_message_entities(message: str) -> dict[str, str]:
        recipient = ""
        content = ""
        patterns = [
            r"(?:给|跟|对)(?P<target>[^\s：:，。,]{1,60})(?:发送消息|发消息|发送|发|说|讲|回复)[:：]?(?P<body>.+)",
            r"(?:发|发送)消息给(?P<target>[^\s：:，。,]{1,60})[:：]?(?P<body>.+)",
            r"在(?P<target>[^\s：:，。,]{1,60})里?(?:发送消息|发消息|发送|发|说|讲)[:：]?(?P<body>.+)",
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
    def _looks_like_message_send_command(message: str, lowered: str) -> bool:
        if re.search(r"(给|跟|在).{1,40}(发|发送|说)", message):
            return True
        if re.search(r"(发|发送)消息给", message):
            return True
        return "send" in lowered

    def _looks_like_message_command(self, message: str, lowered: str) -> bool:
        """Backward-compatible alias for older tests/scripts."""
        return self._looks_like_message_send_command(message, lowered)

    async def _resolve_message_recipient(self, decision: IntentDecision, message: str) -> IntentDecision:
        if decision.standard_action.capability_id != CapabilityId.IM_MESSAGE_SEND:
            return decision
        structured = decision.structured_command if isinstance(decision.structured_command, dict) else {}
        payload = structured.get("payload") if isinstance(structured.get("payload"), dict) else {}
        resolved_payload = await self.recipient_resolver.resolve(message=message, payload=dict(payload))
        if resolved_payload == payload:
            return decision
        updated_structured = dict(structured)
        updated_structured["payload"] = resolved_payload
        return decision.model_copy(
            update={
                "standard_action": self._build_standard_action(
                    intent=decision.intent_type,
                    payload=resolved_payload,
                    capability_id=decision.standard_action.capability_id,
                ),
                "structured_command": updated_structured,
            }
        )

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
