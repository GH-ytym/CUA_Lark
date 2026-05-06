"""Intent service backed by Qwen with schema-first normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import Field

from app.core.config import get_settings
from app.domain.capability_registry import (
    CAPABILITY_REGISTRY,
    CapabilitySpec,
    get_capability_spec,
    missing_execution_fields,
    normalize_payload,
)
from app.domain.enums import CapabilityId, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.schemas.chat import ParsePreviewResponse
from app.services.recipient_resolver import RecipientResolver
from shared.error_codes import normalize_error_code

MESSAGE_CAPABILITIES_WITH_TARGET = {
    capability_id
    for capability_id, spec in CAPABILITY_REGISTRY.items()
    if "chat_hint" in spec.payload_fields
}
LIST_FIELDS = {
    "member_hints",
    "attendees",
    "attendee_ids",
    "user_hints",
    "to_hints",
    "assignee_hints",
    "attachments",
    "cc",
}


@dataclass(frozen=True)
class PlanCandidate:
    """One candidate plan returned from one LLM prompting strategy."""

    source: str
    raw_payload: dict[str, object] | None
    normalized: dict[str, object] | None
    issues: tuple[str, ...]
    llm_error: str | None = None


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

    async def _parse_request_plan_with_llm(self, message: str, context_hint: str) -> IntentDecision | None:
        """Ask the model to plan the full request, including ordered multi-task output."""
        raw_payload, llm_error = await self._request_llm_json(
            system_prompt=self._task_plan_prompt(),
            user_payload={
                "message": message,
                "context_hint": context_hint,
                "current_time": self._current_time_hint(),
            },
            max_tokens=1024,
            contract_hint=self._task_plan_contract_hint(),
            allow_repair=True,
            allow_retry=True,
            timeout_seconds=max(1, int(self.settings.qwen_intent_timeout_seconds)),
        )
        first_candidate = self._build_plan_candidate(
            source="qwen_plan",
            raw_payload=raw_payload,
            llm_error=llm_error,
            original_message=message,
        )
        if first_candidate.raw_payload is None:
            return None if first_candidate.llm_error else self._build_unknown_decision(
                reason="invalid llm output",
                parse_source="qwen_invalid",
            )

        candidate = first_candidate
        if candidate.normalized is None or candidate.issues:
            candidate = await self._authoritative_reask(
                message=message,
                context_hint=context_hint,
                previous_candidate=first_candidate,
            )

        if candidate.normalized is None or candidate.issues:
            return self._build_unknown_decision(
                reason="invalid llm contract",
                parse_source="qwen_invalid",
                raw_llm_payload=candidate.raw_payload or first_candidate.raw_payload,
            )

        candidate = await self._repair_missing_tasks_if_needed(
            candidate=candidate,
            message=message,
            context_hint=context_hint,
        )
        if candidate.normalized is None or candidate.issues:
            return self._build_unknown_decision(
                reason="invalid repaired llm contract",
                parse_source="qwen_invalid",
                raw_llm_payload=candidate.raw_payload or first_candidate.raw_payload,
            )

        return await self._build_decision_from_request_plan(
            normalized=candidate.normalized,
            raw_payload=candidate.raw_payload or {},
            parse_source=candidate.source,
        )

    def _build_plan_candidate(
        self,
        source: str,
        raw_payload: dict[str, object] | None,
        llm_error: str | None,
        original_message: str,
    ) -> PlanCandidate:
        normalized = self._normalize_request_plan_payload(data=raw_payload, original_message=original_message)
        issues = tuple(self._validate_request_plan_payload(normalized))
        return PlanCandidate(
            source=source,
            raw_payload=raw_payload,
            normalized=normalized,
            issues=issues,
            llm_error=llm_error,
        )

    async def _authoritative_reask(
        self,
        message: str,
        context_hint: str,
        previous_candidate: PlanCandidate,
    ) -> PlanCandidate:
        raw_payload, llm_error = await self._request_llm_json(
            system_prompt=self._authoritative_reask_prompt(),
            user_payload={
                "message": message,
                "context_hint": context_hint,
                "current_time": self._current_time_hint(),
                "previous_payload": previous_candidate.raw_payload or {},
                "validation_issues": list(previous_candidate.issues),
                "capability_catalog": self._capability_catalog(),
            },
            max_tokens=1024,
            contract_hint=self._task_plan_contract_hint(),
            allow_repair=True,
            allow_retry=False,
            timeout_seconds=max(1, int(self.settings.qwen_intent_timeout_seconds)),
        )
        if raw_payload is None:
            return previous_candidate
        return self._build_plan_candidate(
            source="qwen_authoritative_reask",
            raw_payload=raw_payload,
            llm_error=llm_error,
            original_message=message,
        )

    async def _repair_missing_tasks_if_needed(
        self,
        candidate: PlanCandidate,
        message: str,
        context_hint: str,
    ) -> PlanCandidate:
        if candidate.normalized is None:
            return candidate

        tasks = candidate.normalized.get("tasks")
        if not isinstance(tasks, list):
            return candidate

        repaired_any = False
        repaired_tasks: list[dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                repaired_tasks.append(task)
                continue

            normalized = task.get("normalized")
            if not isinstance(normalized, dict):
                repaired_tasks.append(task)
                continue

            capability_id = self._resolve_capability_id(normalized)
            if capability_id == CapabilityId.UNKNOWN:
                repaired_tasks.append(task)
                continue

            payload_raw = normalized.get("payload")
            payload = self._finalize_llm_payload(
                capability_id=capability_id,
                payload=dict(payload_raw) if isinstance(payload_raw, dict) else {},
            )
            missing_fields = self._merge_missing_fields(
                self._normalize_missing_fields(normalized.get("missing_fields")),
                self._execution_missing_fields(capability_id=capability_id, payload=payload),
            )
            if not missing_fields:
                repaired_tasks.append(task)
                continue

            repaired_task = await self._repair_single_task_with_llm(
                message=message,
                context_hint=context_hint,
                task=task,
                capability_id=capability_id,
                missing_fields=missing_fields,
            )
            repaired_any = repaired_any or repaired_task is not task
            repaired_tasks.append(repaired_task)

        if not repaired_any:
            return candidate

        normalized_plan = dict(candidate.normalized)
        normalized_plan["tasks"] = repaired_tasks
        raw_payload = dict(candidate.raw_payload or {})
        raw_payload["_task_repairs_applied"] = True
        issues = tuple(self._validate_request_plan_payload(normalized_plan))
        return PlanCandidate(
            source=candidate.source,
            raw_payload=raw_payload,
            normalized=normalized_plan,
            issues=issues,
            llm_error=candidate.llm_error,
        )

    async def _repair_single_task_with_llm(
        self,
        message: str,
        context_hint: str,
        task: dict[str, Any],
        capability_id: CapabilityId,
        missing_fields: list[str],
    ) -> dict[str, Any]:
        normalized = task.get("normalized")
        if not isinstance(normalized, dict):
            return task

        raw_payload, _ = await self._request_llm_json(
            system_prompt=self._task_repair_prompt(),
            user_payload={
                "message": message,
                "context_hint": context_hint,
                "current_time": self._current_time_hint(),
                "task_raw_message": task.get("raw_message", ""),
                "capability_id": capability_id.value,
                "payload": normalized.get("payload") if isinstance(normalized.get("payload"), dict) else {},
                "missing_fields": missing_fields,
                "capability_schema": self._capability_schema(capability_id),
            },
            max_tokens=512,
            contract_hint=self._single_task_contract_hint(capability_id),
            allow_repair=True,
            allow_retry=False,
            timeout_seconds=max(1, int(self.settings.qwen_intent_timeout_seconds)),
        )
        if raw_payload is None:
            return task

        repaired_raw = dict(raw_payload)
        repaired_raw.setdefault("capability_id", capability_id.value)
        repaired_raw.setdefault("c", capability_id.value)
        normalized_repair = self._normalize_intent_payload(repaired_raw)
        if normalized_repair is None or self._resolve_capability_id(normalized_repair) != capability_id:
            return task

        original_missing_count = len(missing_fields)
        original_payload_raw = normalized.get("payload")
        original_payload = self._finalize_llm_payload(
            capability_id=capability_id,
            payload=dict(original_payload_raw) if isinstance(original_payload_raw, dict) else {},
        )
        repaired_payload_raw = normalized_repair.get("payload")
        repaired_payload = self._finalize_llm_payload(
            capability_id=capability_id,
            payload=dict(repaired_payload_raw) if isinstance(repaired_payload_raw, dict) else {},
        )
        repaired_missing = self._execution_missing_fields(capability_id=capability_id, payload=repaired_payload)
        full_repaired_missing = self._merge_missing_fields(
            self._normalize_missing_fields(normalized_repair.get("missing_fields")),
            repaired_missing,
        )
        original_missing = set(missing_fields)
        repaired_missing_set = set(full_repaired_missing)
        if repaired_missing_set - original_missing:
            return task
        if len(full_repaired_missing) >= original_missing_count:
            return task

        repaired_task = dict(task)
        repaired_task["normalized"] = dict(
            normalized_repair,
            payload=repaired_payload,
            missing_fields=full_repaired_missing,
        )
        repaired_task["raw_llm_payload"] = repaired_raw
        return repaired_task

    async def _build_decision_from_request_plan(
        self,
        normalized: dict[str, object],
        raw_payload: dict[str, object],
        parse_source: str,
    ) -> IntentDecision:
        entries = normalized["tasks"]
        decisions: list[IntentDecision] = []
        clauses: list[str] = []
        for entry in entries:
            decision = await self._build_decision_from_normalized(
                normalized=entry["normalized"],
                raw_llm_payload=entry["raw_llm_payload"],
                raw_message=entry["raw_message"],
                parse_source=parse_source,
            )
            decisions.append(decision)
            clauses.append(entry["raw_message"])

        executable_actions = [item.standard_action for item in decisions if item.standard_action.capability_id != CapabilityId.UNKNOWN]
        if not executable_actions:
            return self._build_unknown_decision(
                reason=str(normalized["reason"]).strip() or "no executable action found in request plan",
                parse_source=parse_source,
                action_plan=list(normalized["action_plan"]),
                raw_llm_payload=raw_payload,
            )

        if len(decisions) == 1:
            decision = decisions[0]
            return decision.model_copy(
                update={
                    "parse_source": parse_source,
                    "raw_llm_payload": dict(raw_payload),
                    "task_clauses": clauses,
                }
            )

        missing_fields = self._merge_missing_fields(*(item.missing_fields for item in decisions))
        selected_executor = ExecutorType.CLI if any(
            item.selected_executor == ExecutorType.CLI for item in decisions
        ) else ExecutorType.NONE
        action_plan = list(normalized["action_plan"]) or [
            f"task {index}: {clause[:40]}"
            for index, clause in enumerate(clauses, start=1)
        ][:4]
        structured_command = self._build_multi_structured_command(clauses=clauses, decisions=decisions)
        multi_parse_source = "qwen_multi_plan" if parse_source == "qwen_plan" else f"{parse_source}_multi"

        return IntentDecision(
            intent_type=IntentType.MULTI_TASK,
            reason=f"planned {len(executable_actions)} ordered tasks from one request",
            action_plan=action_plan,
            selected_executor=selected_executor,
            parse_source=multi_parse_source,
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
        normalized_payload = normalize_payload(capability_id, payload) if capability_id != CapabilityId.UNKNOWN else payload
        return {
            "capability_id": capability_id.value,
            "reason": str(self._pick_first(data, "reason", "r", default="parsed by qwen")).strip()[:200] or "parsed by qwen",
            "action_plan": self._normalize_plan(self._pick_first(data, "action_plan", "a")),
            "payload": normalized_payload,
            "missing_fields": self._normalize_missing_fields(self._pick_first(data, "missing_fields", "miss")),
            "handoff_error_code": self._normalize_handoff_error_code(
                self._pick_first(data, "handoff_error_code", "error_code", "code", "ec")
            ),
            "handoff_reason": str(
                self._pick_first(data, "handoff_reason", "error_reason", "error", "er", default="")
            ).strip()[:200],
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
        payload = await self._resolve_calendar_entities_if_needed(capability_id=capability_id, payload=payload)

        missing_fields = self._merge_missing_fields(
            self._normalize_missing_fields(normalized.get("missing_fields")),
            self._execution_missing_fields(capability_id=capability_id, payload=payload),
        )
        structured_command = self._build_structured_command(capability_id=capability_id, payload=payload)
        action = self._build_standard_action(
            capability_id=capability_id,
            payload=payload,
            handoff_error_code=self._normalize_handoff_error_code(normalized.get("handoff_error_code")),
            handoff_reason=str(normalized.get("handoff_reason", "")).strip(),
        )

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

    def _finalize_llm_payload(self, capability_id: CapabilityId, payload: dict[str, Any]) -> dict[str, object]:
        normalized = normalize_payload(capability_id, payload)
        normalized = self._coerce_payload_types(normalized)
        spec = get_capability_spec(capability_id)
        if spec is not None and spec.default_identity:
            normalized["identity"] = self._normalize_identity(
                normalized.get("identity"),
                default_identity=spec.default_identity,
            )
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

    async def _resolve_calendar_entities_if_needed(
        self,
        capability_id: CapabilityId,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if capability_id == CapabilityId.CALENDAR_CREATE:
            return await self._resolve_calendar_attendees(payload=payload)
        if capability_id == CapabilityId.CALENDAR_FREEBUSY:
            return await self._resolve_calendar_freebusy_user(payload=payload)
        return payload

    async def _resolve_calendar_attendees(self, payload: dict[str, object]) -> dict[str, object]:
        resolved = dict(payload)
        attendee_ids = self._normalize_id_list(resolved.get("attendee_ids"))
        unresolved_names = [str(item).strip() for item in resolved.get("attendees", []) if str(item).strip()]
        candidates: list[dict[str, object]] = []
        unresolved_count = 0
        for name in unresolved_names:
            one = await self.recipient_resolver.resolve(
                payload={"chat_hint": name, "chat_id": "", "user_id": "", "text": ""}
            )
            user_id = str(one.get("user_id", "")).strip()
            chat_id = str(one.get("chat_id", "")).strip()
            if user_id:
                attendee_ids.append(user_id)
                continue
            if chat_id:
                attendee_ids.append(chat_id)
                continue
            unresolved_count += 1
            raw_candidates = one.get("resolution_candidates")
            if isinstance(raw_candidates, list):
                candidates.extend(item for item in raw_candidates if isinstance(item, dict))

        resolved["attendee_ids"] = self._dedupe_list(attendee_ids)
        if unresolved_count:
            resolved["resolution_status"] = "needs_confirmation"
            resolved["resolution_reason"] = "calendar_attendee_ambiguous" if candidates else "calendar_attendee_unresolved"
            resolved["resolution_candidates"] = candidates[:3]
        elif unresolved_names:
            resolved["resolution_status"] = "resolved"
            resolved["resolution_method"] = "calendar_recipient_resolver"
        return resolved

    async def _resolve_calendar_freebusy_user(self, payload: dict[str, object]) -> dict[str, object]:
        resolved = dict(payload)
        if str(resolved.get("user_id", "")).strip():
            return resolved
        hints = [str(item).strip() for item in resolved.get("user_hints", []) if str(item).strip()]
        if not hints:
            return resolved
        one = await self.recipient_resolver.resolve(
            payload={"chat_hint": hints[0], "chat_id": "", "user_id": "", "text": ""}
        )
        user_id = str(one.get("user_id", "")).strip()
        if user_id:
            resolved["user_id"] = user_id
            resolved["resolution_status"] = "resolved"
            resolved["resolution_method"] = "calendar_recipient_resolver"
            return resolved
        raw_candidates = one.get("resolution_candidates")
        if isinstance(raw_candidates, list):
            resolved["resolution_candidates"] = [item for item in raw_candidates if isinstance(item, dict)][:3]
        resolved["resolution_status"] = "needs_confirmation"
        resolved["resolution_reason"] = "calendar_user_ambiguous" if resolved.get("resolution_candidates") else "calendar_user_unresolved"
        return resolved

    def _validate_request_plan_payload(self, normalized: dict[str, object] | None) -> list[str]:
        if normalized is None:
            return ["plan is not a valid object"]

        tasks = normalized.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            return ["plan must contain at least one task"]

        issues: list[str] = []
        for index, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                issues.append(f"task {index} is not an object")
                continue

            raw_message = str(task.get("raw_message", "")).strip()
            if not raw_message:
                issues.append(f"task {index} missing raw_message")

            task_payload = task.get("normalized")
            if not isinstance(task_payload, dict):
                issues.append(f"task {index} missing normalized payload")
                continue

            capability_id = self._resolve_capability_id(task_payload)
            if capability_id == CapabilityId.UNKNOWN:
                issues.append(f"task {index} has unknown capability")
                continue

            spec = get_capability_spec(capability_id)
            if spec is None:
                issues.append(f"task {index} capability has no registry schema: {capability_id.value}")
                continue

            raw_llm_payload = task.get("raw_llm_payload")
            raw_llm_payload = raw_llm_payload if isinstance(raw_llm_payload, dict) else {}
            payload_raw = self._pick_first(raw_llm_payload, "payload", "p", "entities")
            extra_fields = self._payload_fields_outside_schema(
                spec=spec,
                payload=dict(payload_raw) if isinstance(payload_raw, dict) else {},
            )
            if extra_fields:
                joined = ", ".join(extra_fields)
                issues.append(f"task {index} payload contains fields outside schema for {capability_id.value}: {joined}")
        return issues

    @staticmethod
    def _payload_fields_outside_schema(spec: CapabilitySpec, payload: dict[str, object]) -> list[str]:
        schema_fields = set(spec.payload_fields) | set(spec.aliases)
        return sorted(str(field_name) for field_name in payload if str(field_name) not in schema_fields)

    @staticmethod
    def _execution_missing_fields(capability_id: CapabilityId, payload: dict[str, object]) -> list[str]:
        return IntentService._merge_missing_fields(missing_execution_fields(capability_id, payload))

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
            "Required task fields: m, c, p. Optional task fields: miss, ec, er. "
            "Optional top-level fields: r, a. Optional task fields: r, a. "
            "t must be an ordered array. Each task object means: m=raw_message, c=capability_id, p=payload, "
            "miss=missing_fields, ec=standard_error_code, er=handoff_reason. "
            "Long field names are allowed for compatibility, but always prefer the compact keys. "
            "Do not rely on punctuation alone. Infer task boundaries from semantics, ordering words, and dependencies. "
            "If the user gives 3-4 actions in one sentence, keep all of them in order inside tasks. "
            "Never invent chat_id, user_id, message_id, thread_id, spreadsheet_token, doc token, or any opaque identifier. "
            "Use current_time from the user payload as the reference for relative dates and times. "
            "For calendar.create, calendar.agenda, and calendar.freebusy, convert relative dates and times into absolute "
            "ISO 8601 strings with timezone offset; default timezone is Asia/Shanghai. "
            "Do not pass vague calendar times such as tomorrow, afternoon, or next week in start_time/end_time. "
            "For calendar.create, put participant names in attendees and leave attendee_ids empty unless the user supplied an opaque ou_/oc_/omm_ id. "
            "For calendar.freebusy, put the queried person's name in user_hints and leave user_id empty unless the user supplied an opaque ou_ id. "
            "Leave unknown strings empty, unknown arrays empty, and unknown records empty. "
            "Use only these capability schemas: "
            f"{IntentService._capability_catalog_text()} "
            "If the task cannot be executed by CLI but can be completed in the Feishu desktop UI, set ec to one standard "
            "integer error code from the catalog instead of inventing placeholders. Use 4 for missing or unresolved execution "
            "input, 7 for explicit handoff required, 2 for unsupported CLI capability, 5 for uncategorized execution failure. "
            "If a required execution argument is missing, list it in missing_fields instead of guessing. "
            "Do not drop recipient names from payload.chat_hint just because an id is unknown. "
            "For user-visible names, descriptions, titles, messages, and queries, preserve the user wording in the matching schema field. "
            "Keep each raw_message as a short natural-language clause that corresponds to one task and preserves the user intended order."
        )

    @staticmethod
    def _task_plan_contract_hint() -> str:
        return (
            '{"t":['
            '{"m":"send a status note to Alex","c":"im.message_send",'
            '"p":{"chat_hint":"Alex","chat_id":"","user_id":"","text":"The rollout is ready.","identity":"user"},"miss":[],"ec":null},'
            '{"m":"create a follow-up document","c":"docs.create",'
            '"p":{"title":"Rollout follow-up","content":"","folder_token":""},"miss":[]},'
            '{"m":"schedule the review tomorrow at 3pm","c":"calendar.create",'
            '"p":{"title":"Review","start_time":"2026-05-06T15:00:00+08:00","end_time":"2026-05-06T16:00:00+08:00",'
            '"attendees":["Alex"],"attendee_ids":[],"identity":"user"},"miss":[]}'
            ']}'
        )

    @staticmethod
    def _authoritative_reask_prompt() -> str:
        return (
            "You are the authoritative validator and replanner for a Feishu automation agent. "
            "The previous JSON did not satisfy the capability registry. "
            "Re-read the original user request, validation issues, previous payload, and capability catalog. "
            "Return one corrected JSON object only using the compact plan contract: top-level t array; each task has m, c, p, optional miss. "
            "Use only registered capability IDs, keep task order, and keep payload keys inside each capability schema. "
            "Do not invent opaque IDs or tokens. Put unresolved required fields in miss."
        )

    @staticmethod
    def _task_repair_prompt() -> str:
        return (
            "You repair exactly one already-classified Feishu automation task. "
            "Return one JSON object only for the same capability. "
            "Use the given capability schema and original request to fill only fields that are supported by that schema. "
            "If the missing value is not present in the user request or context, leave the field empty and keep it in miss. "
            "Do not change the capability and do not invent opaque IDs or tokens."
        )

    @staticmethod
    def _single_task_contract_hint(capability_id: CapabilityId) -> str:
        schema = IntentService._capability_schema(capability_id)
        payload = {str(field_name): "" for field_name in schema.get("payload_fields", [])}
        for field_name in schema.get("array_fields", []):
            payload[str(field_name)] = []
        for field_name in schema.get("object_fields", []):
            payload[str(field_name)] = {}
        if "limit" in payload:
            payload["limit"] = 20
        return json.dumps(
            {"c": capability_id.value, "p": payload, "miss": list(schema.get("required_fields", []))},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _capability_catalog() -> list[dict[str, object]]:
        return [
            IntentService._capability_schema(capability_id)
            for capability_id in sorted(CAPABILITY_REGISTRY, key=lambda item: item.value)
        ] + [{"capability_id": CapabilityId.UNKNOWN.value, "payload_fields": [], "required_fields": []}]

    @staticmethod
    def _capability_catalog_text() -> str:
        return json.dumps(
            IntentService._capability_catalog(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _capability_schema(capability_id: CapabilityId) -> dict[str, object]:
        spec = get_capability_spec(capability_id)
        if spec is None:
            return {
                "capability_id": capability_id.value,
                "payload_fields": [],
                "required_fields": [],
            }

        return {
            "capability_id": spec.capability_id.value,
            "payload_fields": list(spec.payload_fields),
            "required_fields": list(spec.required_fields),
            "required_field_groups": [
                {"representative": representative, "any_of": list(fields)}
                for representative, fields in spec.required_field_groups
            ],
            "array_fields": [
                field_name
                for field_name in spec.payload_fields
                if field_name.endswith("_hints")
                or field_name.endswith("_ids")
                or field_name in {"attendees", "attachments", "cc"}
            ],
            "object_fields": [
                field_name
                for field_name in spec.payload_fields
                if field_name in {"record"}
            ],
        }

    @staticmethod
    def _resolve_capability_id(normalized: dict[str, object]) -> CapabilityId:
        return IntentService._to_capability_id(str(normalized.get("capability_id", "")))

    @staticmethod
    def _to_capability_id(value: str) -> CapabilityId:
        normalized = value.strip().lower().replace("-", ".")
        aliases = {
            "message.send": "im.message_send",
            "send.message": "im.message_send",
            "message.reply": "im.messages_reply",
            "messages.reply": "im.messages_reply",
            "message.search": "im.messages_search",
            "messages.search": "im.messages_search",
            "chat.messages.list": "im.chat_messages_list",
            "chat.search": "im.chat_search",
            "chat.create": "im.chat_create",
            "doc.create": "docs.create",
            "doc.update": "docs.update",
            "doc.search": "docs.search",
            "sheet.update": "sheets.update",
            "sheet.read": "sheets.read",
            "base.record.create": "base.record_create",
        }
        compact = normalized.replace("_", ".")
        for candidate in (normalized, aliases.get(normalized, ""), compact, aliases.get(compact, "")):
            try:
                return CapabilityId(candidate)
            except ValueError:
                continue
        return CapabilityId.UNKNOWN

    @staticmethod
    def _intent_for_capability(capability_id: CapabilityId) -> IntentType:
        spec = get_capability_spec(capability_id)
        return spec.intent_type if spec is not None else IntentType.UNKNOWN

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
    def _normalize_id_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]

    @staticmethod
    def _dedupe_list(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped

    @staticmethod
    def _current_time_hint() -> str:
        try:
            tzinfo = ZoneInfo("Asia/Shanghai")
        except ZoneInfoNotFoundError:
            tzinfo = timezone(timedelta(hours=8), name="Asia/Shanghai")
        return datetime.now(tzinfo).isoformat()

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

    @staticmethod
    def _normalize_handoff_error_code(value: object) -> int | None:
        code = normalize_error_code(value)
        return int(code) if code is not None else None

    def _build_standard_action(
        self,
        capability_id: CapabilityId,
        payload: dict[str, object],
        handoff_error_code: int | None = None,
        handoff_reason: str = "",
    ) -> StandardAction:
        intent = self._intent_for_capability(capability_id)
        return StandardAction(
            capability_id=capability_id,
            payload=payload,
            executor_hint=self._executor_for(capability_id),
            intent_type=intent,
            handoff_error_code=self._normalize_handoff_error_code(handoff_error_code),
            handoff_reason=str(handoff_reason).strip()[:200],
        )

