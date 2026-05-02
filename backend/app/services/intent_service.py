"""Intent service backed by Qwen with schema-first normalization."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import Field

from app.core.config import get_settings
from app.domain.capability_registry import missing_required_fields, normalize_payload
from app.domain.enums import CapabilityId, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.schemas.chat import ParsePreviewResponse
from app.services.recipient_resolver import RecipientResolver

MESSAGE_CAPABILITIES_WITH_TARGET = {
    CapabilityId.IM_MESSAGE_SEND,
    CapabilityId.IM_MESSAGES_SEARCH,
    CapabilityId.IM_CHAT_MESSAGES_LIST,
}
LIST_FIELDS = {"member_hints", "attendees", "user_hints", "to_hints", "assignee_hints", "attachments", "cc"}
BOT_IDENTITY_CAPABILITIES = {CapabilityId.IM_CHAT_CREATE}
USER_IDENTITY_CAPABILITIES = {
    CapabilityId.IM_MESSAGE_SEND,
    CapabilityId.IM_MESSAGES_REPLY,
    CapabilityId.IM_MESSAGES_SEARCH,
    CapabilityId.IM_CHAT_MESSAGES_LIST,
    CapabilityId.IM_CHAT_SEARCH,
}


class IntentDecision(ParsePreviewResponse):
    """Intent decision plus structured action output."""

    action_plan: list[str]
    selected_executor: ExecutorType
    parse_source: str = "qwen"
    missing_fields: list[str] = Field(default_factory=list)
    standard_action: StandardAction = Field(default_factory=StandardAction)
    planned_actions: list[StandardAction] = Field(default_factory=list)
    task_clauses: list[str] = Field(default_factory=list)
    structured_command: dict[str, Any] = Field(default_factory=dict)
    raw_llm_payload: dict[str, Any] = Field(default_factory=dict)


class IntentService:
    """Resolve user requests by asking Qwen for a strict structured action."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.recipient_resolver = RecipientResolver()

    async def parse(self, message: str, context_hint: str = "") -> IntentDecision:
        """Parse one natural-language request into a standard action."""
        if not self.settings.dashscope_api_key:
            return self._build_unknown_decision(
                reason="qwen api key is not configured",
                parse_source="llm_unavailable",
            )

        decision = await self._parse_request_plan_with_llm(message=message, context_hint=context_hint)
        if decision is not None:
            return decision

        parse_source = "qwen_required" if self.settings.intent_require_llm else "qwen_failed"
        return self._build_unknown_decision(
            reason="qwen parse failed",
            parse_source=parse_source,
        )

    async def _parse_with_llm(self, message: str, context_hint: str) -> IntentDecision | None:
        """Backward-compatible alias for the planner parse path."""
        return await self._parse_request_plan_with_llm(message=message, context_hint=context_hint)

    async def _parse_request_plan_with_llm(self, message: str, context_hint: str) -> IntentDecision | None:
        """Ask the model to plan the full request, including ordered multi-task output."""
        raw_payload, llm_error = await self._request_llm_json(
            system_prompt=self._task_plan_prompt(),
            user_payload={"message": message, "context_hint": context_hint},
            max_tokens=1024,
            contract_hint=self._task_plan_contract_hint(),
            allow_repair=True,
            allow_retry=True,
            timeout_seconds=max(1, int(self.settings.qwen_intent_timeout_seconds)),
        )
        if raw_payload is None:
            return None if llm_error else self._build_unknown_decision(reason="invalid llm output", parse_source="qwen_invalid")

        normalized = self._normalize_request_plan_payload(data=raw_payload, original_message=message)
        if normalized is None:
            return self._build_unknown_decision(
                reason="invalid llm contract",
                parse_source="qwen_invalid",
                raw_llm_payload=raw_payload,
            )

        entries = normalized["tasks"]
        decisions: list[IntentDecision] = []
        clauses: list[str] = []
        for entry in entries:
            decision = await self._build_decision_from_normalized(
                normalized=entry["normalized"],
                raw_llm_payload=entry["raw_llm_payload"],
                raw_message=entry["raw_message"],
                parse_source="qwen_plan",
            )
            decisions.append(decision)
            clauses.append(entry["raw_message"])

        executable_actions = [item.standard_action for item in decisions if item.standard_action.capability_id != CapabilityId.UNKNOWN]
        if not executable_actions:
            return self._build_unknown_decision(
                reason=str(normalized["reason"]).strip() or "no executable action found in request plan",
                parse_source="qwen_plan",
                action_plan=list(normalized["action_plan"]),
                raw_llm_payload=raw_payload,
            )

        if len(decisions) == 1:
            decision = decisions[0]
            return decision.model_copy(
                update={
                    "parse_source": "qwen_plan",
                    "raw_llm_payload": dict(raw_payload),
                    "task_clauses": clauses,
                }
            )

        missing_fields = self._merge_missing_fields(*(item.missing_fields for item in decisions))
        selected_executor = ExecutorType.CLI if any(
            item.selected_executor == ExecutorType.CLI for item in decisions
        ) else ExecutorType.NONE
        action_plan = list(normalized["action_plan"]) or [
            f"任务{index}: {clause[:40]}"
            for index, clause in enumerate(clauses, start=1)
        ][:4]
        structured_command = self._build_multi_structured_command(clauses=clauses, decisions=decisions)

        return IntentDecision(
            intent_type=IntentType.MULTI_TASK,
            reason=f"planned {len(executable_actions)} ordered tasks from one request",
            action_plan=action_plan,
            selected_executor=selected_executor,
            parse_source="qwen_multi_plan",
            missing_fields=missing_fields,
            standard_action=executable_actions[0],
            planned_actions=[item.standard_action for item in decisions],
            task_clauses=clauses,
            structured_command=structured_command,
            raw_llm_payload=dict(raw_payload),
        )

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

        repair_prompt = (
            "Rewrite the previous model output into one strict JSON object only. "
            f"Required contract: {contract_hint}"
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

        retry_content, retry_error = await self._chat_completion(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        if retry_error:
            return None, f"retry_{retry_error}"

        retry_json = self._safe_json_loads(retry_content)
        if retry_json is not None:
            return retry_json, None
        return None, "invalid_json_retry"

    async def _chat_completion(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> tuple[str, str | None]:
        payload = {
            "model": self.settings.qwen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=max(1, timeout_seconds)) as client:
                response = await client.post(self.settings.qwen_chat_url, headers=headers, json=payload)
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
        """Normalize raw model JSON into one internal contract."""
        if not isinstance(data, dict):
            return None

        payload_raw = self._pick_first(data, "payload", "p", "entities")
        payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        capability_value = str(self._pick_first(data, "capability_id", "c", default="")).strip()
        if not capability_value:
            capability_value = str(self._pick_first(data, "intent_type", "i", default="")).strip()

        capability_id = self._to_capability_id(capability_value)
        if capability_id == CapabilityId.IM_MESSAGE_SEND:
            payload = self._normalize_message_payload(payload)

        normalized_payload = normalize_payload(capability_id, payload) if capability_id != CapabilityId.UNKNOWN else payload
        return {
            "capability_id": capability_id.value,
            "reason": str(self._pick_first(data, "reason", "r", default="parsed by qwen")).strip()[:200] or "parsed by qwen",
            "action_plan": self._normalize_plan(self._pick_first(data, "action_plan", "a")),
            "payload": normalized_payload,
            "missing_fields": self._normalize_missing_fields(self._pick_first(data, "missing_fields", "miss")),
        }

    def _normalize_request_plan_payload(
        self,
        data: dict[str, object] | None,
        original_message: str,
    ) -> dict[str, object] | None:
        if not isinstance(data, dict):
            return None

        tasks_raw = self._pick_first(data, "tasks", "t")
        if isinstance(tasks_raw, list) and tasks_raw:
            tasks: list[dict[str, Any]] = []
            for index, item in enumerate(tasks_raw, start=1):
                if not isinstance(item, dict):
                    continue
                normalized = self._normalize_intent_payload(item)
                if normalized is None:
                    return None
                raw_message = str(self._pick_first(item, "raw_message", "m", default="")).strip() or f"task {index}"
                tasks.append(
                    {
                        "order": index,
                        "raw_message": raw_message,
                        "normalized": normalized,
                        "raw_llm_payload": dict(item),
                    }
                )
            if not tasks:
                return None
            return {
                "intent_type": IntentType.MULTI_TASK.value if len(tasks) > 1 else tasks[0]["normalized"]["capability_id"],
                "reason": str(self._pick_first(data, "reason", "r", default="planned by qwen")).strip()[:200] or "planned by qwen",
                "action_plan": self._normalize_plan(self._pick_first(data, "action_plan", "a")),
                "tasks": tasks,
            }

        normalized = self._normalize_intent_payload(data)
        if normalized is None:
            return None
        return {
            "intent_type": normalized["capability_id"],
            "reason": str(normalized.get("reason", "planned by qwen")).strip()[:200] or "planned by qwen",
            "action_plan": self._normalize_plan(self._pick_first(data, "action_plan", "a")),
            "tasks": [
                {
                    "order": 1,
                    "raw_message": original_message.strip() or "task 1",
                    "normalized": normalized,
                    "raw_llm_payload": dict(data),
                }
            ],
        }

    async def _build_decision_from_normalized(
        self,
        normalized: dict[str, object],
        raw_llm_payload: dict[str, object],
        raw_message: str,
        parse_source: str,
    ) -> IntentDecision:
        capability_id = self._resolve_capability_id(normalized)
        if capability_id == CapabilityId.UNKNOWN:
            return self._build_unknown_decision(
                reason=str(normalized.get("reason", "unknown capability")).strip() or "unknown capability",
                parse_source=parse_source,
                action_plan=self._normalize_plan(normalized.get("action_plan")),
                raw_llm_payload=raw_llm_payload,
            )

        payload_raw = normalized.get("payload")
        payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        payload = self._finalize_llm_payload(capability_id=capability_id, payload=payload)
        payload = await self._resolve_recipient_if_needed(capability_id=capability_id, payload=payload)

        missing_fields = self._merge_missing_fields(
            self._normalize_missing_fields(normalized.get("missing_fields")),
            self._execution_missing_fields(capability_id=capability_id, payload=payload),
        )
        structured_command = self._build_structured_command(capability_id=capability_id, payload=payload)
        action = self._build_standard_action(capability_id=capability_id, payload=payload)

        return IntentDecision(
            intent_type=self._intent_for_capability(capability_id),
            reason=str(normalized.get("reason", "parsed by qwen")).strip()[:200] or "parsed by qwen",
            action_plan=self._normalize_plan(normalized.get("action_plan")),
            selected_executor=self._executor_for(capability_id),
            parse_source=parse_source,
            missing_fields=missing_fields,
            standard_action=action,
            planned_actions=[action],
            task_clauses=[raw_message],
            structured_command=structured_command,
            raw_llm_payload=dict(raw_llm_payload),
        )

    @staticmethod
    def _normalize_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "chat_hint": str(payload.get("chat_hint", payload.get("target", payload.get("recipient", "")))).strip(),
            "chat_id": str(payload.get("chat_id", "")).strip(),
            "user_id": str(payload.get("user_id", "")).strip(),
            "text": str(payload.get("text", payload.get("message", payload.get("message_text", "")))).strip(),
            "identity": str(payload.get("identity", "")).strip(),
        }

    def _finalize_llm_payload(self, capability_id: CapabilityId, payload: dict[str, Any]) -> dict[str, object]:
        normalized = normalize_payload(capability_id, payload)
        normalized = self._coerce_payload_types(normalized)
        if capability_id in BOT_IDENTITY_CAPABILITIES:
            normalized["identity"] = self._normalize_identity(normalized.get("identity"), default_identity="bot")
        elif capability_id in USER_IDENTITY_CAPABILITIES:
            normalized["identity"] = self._normalize_identity(normalized.get("identity"), default_identity="user")
        return normalized

    def _coerce_payload_types(self, payload: dict[str, object]) -> dict[str, object]:
        coerced = dict(payload)
        for field_name in LIST_FIELDS:
            if field_name not in coerced:
                continue
            value = coerced.get(field_name)
            if isinstance(value, list):
                coerced[field_name] = [str(item).strip() for item in value if str(item).strip()]
            else:
                text = str(value or "").strip()
                coerced[field_name] = [text] if text else []
        if "limit" in coerced and not isinstance(coerced.get("limit"), int):
            try:
                coerced["limit"] = int(str(coerced.get("limit", "")).strip())
            except ValueError:
                coerced["limit"] = 20
        return coerced

    @staticmethod
    def _normalize_identity(value: object, default_identity: str) -> str:
        identity = str(value or "").strip().lower()
        return identity if identity in {"bot", "user"} else default_identity

    async def _resolve_recipient_if_needed(self, capability_id: CapabilityId, payload: dict[str, object]) -> dict[str, object]:
        if capability_id not in MESSAGE_CAPABILITIES_WITH_TARGET:
            return payload
        return await self.recipient_resolver.resolve(payload=dict(payload))

    @staticmethod
    def _execution_missing_fields(capability_id: CapabilityId, payload: dict[str, object]) -> list[str]:
        missing = missing_required_fields(capability_id, payload)
        if capability_id in MESSAGE_CAPABILITIES_WITH_TARGET:
            has_target = any(str(payload.get(field_name, "")).strip() for field_name in ("chat_hint", "chat_id", "user_id"))
            if not has_target:
                missing.append("chat_hint")
        if capability_id == CapabilityId.IM_MESSAGES_REPLY:
            has_reply_target = any(str(payload.get(field_name, "")).strip() for field_name in ("message_id", "thread_id", "message_hint"))
            if not has_reply_target:
                missing.append("message_hint")
        return IntentService._merge_missing_fields(missing)

    def _build_unknown_decision(
        self,
        reason: str,
        parse_source: str,
        action_plan: list[str] | None = None,
        raw_llm_payload: dict[str, Any] | None = None,
    ) -> IntentDecision:
        structured_command = {
            "intent_type": IntentType.UNKNOWN.value,
            "capability_id": CapabilityId.UNKNOWN.value,
            "payload": {},
        }
        return IntentDecision(
            intent_type=IntentType.UNKNOWN,
            reason=reason,
            action_plan=action_plan or ["ask user for a clearer instruction"],
            selected_executor=ExecutorType.NONE,
            parse_source=parse_source,
            missing_fields=[],
            standard_action=self._build_standard_action(capability_id=CapabilityId.UNKNOWN, payload={}),
            planned_actions=[],
            task_clauses=[],
            structured_command=structured_command,
            raw_llm_payload=raw_llm_payload or {},
        )

    @staticmethod
    def _task_plan_prompt() -> str:
        return (
            "You are the task planner and intent parser for a Feishu automation agent. "
            "Read the full user request and decide whether it contains one task or multiple ordered tasks. "
            "Return exactly one JSON object and nothing else. "
            "Use the minimal compact JSON schema for stability. "
            "Required top-level field: t. "
            "Required task fields: m, c, p. Optional task field: miss. "
            "Optional top-level fields: r, a. Optional task fields: r, a. "
            "t must be an ordered array. Each task object means: m=raw_message, c=capability_id, p=payload, miss=missing_fields. "
            "Long field names are allowed for compatibility, but always prefer the compact keys. "
            "Do not rely on punctuation alone. Infer task boundaries from semantics, ordering words, and dependencies. "
            "If the user gives 3-4 actions in one sentence, keep all of them in order inside tasks. "
            "Never invent chat_id, user_id, message_id, thread_id, spreadsheet_token, doc token, or any opaque identifier. "
            "Leave unknown strings empty and unknown arrays empty. "
            "capability_id must be one of: "
            "im.message_send, im.messages_reply, im.messages_search, im.chat_messages_list, im.chat_search, im.chat_create, "
            "calendar.create, calendar.reschedule, calendar.agenda, calendar.freebusy, "
            "docs.create, docs.update, docs.search, sheets.update, sheets.read, "
            "contact.search, task.create, mail.send, base.record_create, unknown. "
            "For im.message_send payload use: chat_hint, chat_id, user_id, text, identity. "
            "For im.messages_reply payload use: message_id, thread_id, message_hint, text, reply_in_thread, identity. "
            "For im.messages_search payload use: query, chat_hint, chat_id, sender_hint, start_time, end_time, limit, identity. "
            "For im.chat_messages_list payload use: chat_hint, chat_id, user_id, start_time, end_time, limit, identity. "
            "For im.chat_search payload use: query, member_hints, limit, identity. "
            "For im.chat_create payload use: name, member_hints, description, identity. "
            "For calendar.create payload use: title, start_time, end_time, attendees, location. "
            "For calendar.reschedule payload use: event_hint, source_time, target_time. "
            "For calendar.agenda payload use: time_range, user_hints. "
            "For calendar.freebusy payload use: time_range, user_hints. "
            "For docs.create payload use: title, content, folder_token. "
            "For docs.update payload use: title, content, doc_token. "
            "For docs.search payload use: query. "
            "For sheets.update payload use: spreadsheet_token, sheet_id, cell, value. "
            "For sheets.read payload use: spreadsheet_token, sheet_id, cell. "
            "For contact.search payload use: query. "
            "For task.create payload use: title, assignee_hints, due_time, description. "
            "For mail.send payload use: subject, body, to_hints, cc, attachments. "
            "For base.record_create payload use: base_hint, table_hint, record. "
            "If a required execution argument is missing, list it in missing_fields instead of guessing. "
            "Extraction rules: "
            "When the user says 'give X a message', 'send a message to X', 'tell X ...', or the Chinese forms '给X发消息', '发送消息给X', '跟X说', put X into payload.chat_hint. "
            "When the user asks to search or list messages in one chat, keep that chat name in payload.chat_hint. "
            "Do not drop recipient names from payload.chat_hint just because the id is unknown. "
            "For task.create, keep the core task wording in payload.title; if there is a deadline, copy it into due_time but do not over-shorten title. "
            "Keep each raw_message as a short natural-language clause that corresponds to one task and preserves the user's intended order."
        )

    @staticmethod
    def _task_plan_contract_hint() -> str:
        return (
            '{"t":['
            '{"m":"先给项目群发消息：今晚九点发布","c":"im.message_send",'
            '"p":{"chat_hint":"项目群","chat_id":"","user_id":"","text":"今晚九点发布","identity":"user"},"miss":[]},'
            '{"m":"然后创建文档，标题叫发布复盘","c":"docs.create",'
            '"p":{"title":"发布复盘","content":"","folder_token":""},"miss":[]}'
            ']}'
        )

    @staticmethod
    def _resolve_capability_id(normalized: dict[str, object]) -> CapabilityId:
        return IntentService._to_capability_id(str(normalized.get("capability_id", "")))

    @staticmethod
    def _to_capability_id(value: str) -> CapabilityId:
        raw = value.strip().lower()
        alias = {item.value: item for item in CapabilityId}
        alias.update(
            {
                "message.send": CapabilityId.IM_MESSAGE_SEND,
                "send.message": CapabilityId.IM_MESSAGE_SEND,
                "message.reply": CapabilityId.IM_MESSAGES_REPLY,
                "messages.reply": CapabilityId.IM_MESSAGES_REPLY,
                "message.search": CapabilityId.IM_MESSAGES_SEARCH,
                "messages.search": CapabilityId.IM_MESSAGES_SEARCH,
                "chat.messages.list": CapabilityId.IM_CHAT_MESSAGES_LIST,
                "chat.search": CapabilityId.IM_CHAT_SEARCH,
                "chat.create": CapabilityId.IM_CHAT_CREATE,
                "calendar.create": CapabilityId.CALENDAR_CREATE,
                "calendar.reschedule": CapabilityId.CALENDAR_RESCHEDULE,
                "calendar.agenda": CapabilityId.CALENDAR_AGENDA,
                "calendar.freebusy": CapabilityId.CALENDAR_FREEBUSY,
                "doc.create": CapabilityId.DOC_CREATE,
                "docs.create": CapabilityId.DOC_CREATE,
                "doc.update": CapabilityId.DOC_UPDATE,
                "docs.update": CapabilityId.DOC_UPDATE,
                "doc.search": CapabilityId.DOC_SEARCH,
                "docs.search": CapabilityId.DOC_SEARCH,
                "sheet.update": CapabilityId.SHEET_UPDATE,
                "sheets.update": CapabilityId.SHEET_UPDATE,
                "sheet.read": CapabilityId.SHEET_READ,
                "sheets.read": CapabilityId.SHEET_READ,
                "contact.search": CapabilityId.CONTACT_SEARCH,
                "task.create": CapabilityId.TASK_CREATE,
                "mail.send": CapabilityId.MAIL_SEND,
                "base.record.create": CapabilityId.BASE_RECORD_CREATE,
                "base.record_create": CapabilityId.BASE_RECORD_CREATE,
            }
        )
        candidates = (
            raw,
            raw.replace("-", "."),
            raw.replace("_", "."),
            raw.replace("-", "_"),
        )
        for candidate in candidates:
            resolved = alias.get(candidate)
            if resolved is not None:
                return resolved
        return CapabilityId.UNKNOWN

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

    @staticmethod
    def _executor_for(capability_id: CapabilityId) -> ExecutorType:
        return ExecutorType.NONE if capability_id == CapabilityId.UNKNOWN else ExecutorType.CLI

    @staticmethod
    def _normalize_plan(raw_plan: object) -> list[str]:
        if isinstance(raw_plan, list):
            normalized = [str(item).strip()[:60] for item in raw_plan if str(item).strip()]
            if normalized:
                return normalized[:4]
        if isinstance(raw_plan, str) and raw_plan.strip():
            return [raw_plan.strip()[:60]]
        return ["call lark-cli with the structured payload"]

    @staticmethod
    def _normalize_missing_fields(raw_missing_fields: object) -> list[str]:
        if not isinstance(raw_missing_fields, list):
            return []
        return IntentService._merge_missing_fields([str(item).strip() for item in raw_missing_fields if str(item).strip()])

    @staticmethod
    def _merge_missing_fields(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for field_name in group:
                normalized = str(field_name).strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
        return merged

    @staticmethod
    def _pick_first(data: dict[str, object], *keys: str, default: object = None) -> object:
        for key in keys:
            if key in data:
                return data[key]
        return default

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
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def _build_structured_command(self, capability_id: CapabilityId, payload: dict[str, object]) -> dict[str, Any]:
        return {
            "intent_type": self._intent_for_capability(capability_id).value,
            "capability_id": capability_id.value,
            "payload": normalize_payload(capability_id, dict(payload)),
        }

    def _build_multi_structured_command(
        self,
        clauses: list[str],
        decisions: list[IntentDecision],
    ) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        for index, (clause, decision) in enumerate(zip(clauses, decisions, strict=False), start=1):
            action = decision.standard_action
            tasks.append(
                {
                    "order": index,
                    "raw_message": clause,
                    "intent_type": action.intent_type.value,
                    "capability_id": action.capability_id.value,
                    "payload": dict(action.payload),
                    "missing_fields": list(decision.missing_fields),
                }
            )
        return {
            "intent_type": IntentType.MULTI_TASK.value,
            "tasks": tasks,
        }

    def _build_standard_action(self, capability_id: CapabilityId, payload: dict[str, object]) -> StandardAction:
        intent = self._intent_for_capability(capability_id)
        return StandardAction(
            capability_id=capability_id,
            payload=payload,
            executor_hint=self._executor_for(capability_id),
            intent_type=intent,
        )

