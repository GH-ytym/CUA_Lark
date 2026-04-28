"""Resolve message recipients from local SQLite directory with MiniMax ranking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
import inspect
from pathlib import Path
import re
import sqlite3
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import get_settings

Picker = Callable[[str, list["RecipientCandidate"]], Awaitable[int | None] | int | None]


@dataclass(frozen=True)
class RecipientCandidate:
    """One recipient candidate from local SQLite directory."""

    entity_type: str
    entity_id: str
    name: str
    score: float


class RecipientResolver:
    """Resolve message recipient by name using local index plus MiniMax fuzzy ranking."""

    GENERIC_HINTS = {
        "他们",
        "她们",
        "他",
        "她",
        "ta",
        "同学",
        "同事",
        "老师",
        "朋友",
        "大家",
        "有人",
        "某人",
        "那个人",
        "这个人",
        "合适的人",
        "相关同学",
        "相关人员",
    }
    TYPO_MAP = {
        "陖": "俊",
        "濟": "济",
        "傢": "家",
        "蘭": "兰",
    }

    def __init__(self, sqlite_path: str | None = None, picker: Picker | None = None) -> None:
        self.settings = get_settings()
        self.sqlite_path = self._resolve_sqlite_path(sqlite_path or self.settings.recipient_sqlite_path)
        self._picker = picker
        self._top_k = max(1, int(self.settings.recipient_resolver_top_k))

    async def resolve(self, message: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fill chat_id/user_id from local directory when only name hint is available."""
        chat_id = str(payload.get("chat_id", "")).strip()
        user_id = str(payload.get("user_id", "")).strip()
        if chat_id or user_id:
            resolved = dict(payload)
            resolved["resolution_status"] = "resolved"
            resolved["resolution_method"] = "provided_id"
            return resolved
        hint = str(payload.get("chat_hint", "")).strip() or self._extract_hint(message)
        if not hint:
            return self._mark_needs_confirmation(
                payload=payload,
                reason="missing_hint",
                candidates=[],
            )
        candidates = self._search_candidates(hint)
        if not candidates:
            return self._mark_needs_confirmation(
                payload=payload,
                reason="no_candidate",
                candidates=[],
            )
        selected_index = self._pick_by_rules(hint, candidates)
        ambiguous = self._is_ambiguous(hint, candidates)
        if self._should_try_llm_pick(hint=hint, candidates=candidates, selected_index=selected_index, ambiguous=ambiguous):
            llm_index = await self._pick_index(hint, candidates)
            if llm_index is not None:
                selected_index = llm_index
        if selected_index is None:
            return self._mark_needs_confirmation(
                payload=payload,
                reason="ambiguous_or_low_confidence",
                candidates=candidates,
            )
        selected = candidates[selected_index]
        resolved = dict(payload)
        resolved["resolved_name"] = selected.name
        resolved["resolution_status"] = "resolved"
        resolved["resolution_method"] = "llm" if self.settings.recipient_resolver_use_llm and ambiguous else "rules"
        resolved["resolution_score"] = round(float(selected.score), 4)
        if selected.entity_type == "chat":
            resolved["chat_id"] = selected.entity_id
            resolved["user_id"] = ""
        else:
            resolved["user_id"] = selected.entity_id
            resolved["chat_id"] = ""
        return resolved

    def _search_candidates(self, hint: str) -> list[RecipientCandidate]:
        db_path = Path(self.sqlite_path)
        if not db_path.exists():
            return []
        hint_text = self._normalize_text(hint)
        if not hint_text:
            return []
        query_like = f"%{hint_text}%"
        rows: list[tuple[str, str, str, str]] = []
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, name, searchable_text
                FROM recipients
                WHERE searchable_text LIKE ?
                LIMIT 400
                """,
                (query_like,),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    """
                    SELECT entity_type, entity_id, name, searchable_text
                    FROM recipients
                    LIMIT 400
                    """
                ).fetchall()
        ranked: list[RecipientCandidate] = []
        for entity_type, entity_id, name, searchable_text in rows:
            score = self._score(hint_text, searchable_text or name)
            ranked.append(
                RecipientCandidate(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    name=name,
                    score=score,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: self._top_k]

    async def _pick_index(self, hint: str, candidates: list[RecipientCandidate]) -> int | None:
        if self._picker is not None:
            picked = self._picker(hint, candidates)
            if inspect.isawaitable(picked):
                return await picked
            return picked if isinstance(picked, int) else None
        if not self.settings.recipient_resolver_use_llm:
            return None
        return await self._pick_index_with_minimax(hint, candidates)

    async def _pick_index_with_minimax(self, hint: str, candidates: list[RecipientCandidate]) -> int | None:
        if not self.settings.minimax_api_key:
            return None
        prompt = (
            "你是飞书接收对象匹配器。"
            "用户提供一个接收对象名称，请在候选列表中选最匹配的一项。"
            "只输出 JSON，字段: match_index(int, -1 表示无法确定), confidence(0-1), reason(字符串)。"
        )
        candidates_json = [
            {
                "index": idx,
                "entity_type": item.entity_type,
                "name": item.name,
                "entity_id": item.entity_id,
                "rule_score": round(item.score, 4),
            }
            for idx, item in enumerate(candidates)
        ]
        payload = {
            "model": self.settings.minimax_model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"target_name": hint, "candidates": candidates_json},
                        ensure_ascii=False,
                    ),
                },
            ],
            "max_tokens": 200,
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.minimax_api_key}",
            "Content-Type": "application/json",
        }
        try:
            timeout_seconds = max(1, int(self.settings.minimax_recipient_timeout_seconds))
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(self.settings.minimax_chat_url, headers=headers, json=payload)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            return None
        parsed = self._safe_json_loads(content)
        if parsed is None:
            return None
        confidence = float(parsed.get("confidence", 0))
        match_index = int(parsed.get("match_index", -1))
        if confidence < 0.55 or match_index < 0 or match_index >= len(candidates):
            return None
        return match_index

    @staticmethod
    def _pick_by_rules(hint: str, candidates: list[RecipientCandidate]) -> int | None:
        if not candidates:
            return None
        if RecipientResolver._is_generic_hint(hint):
            return None
        hint_text = RecipientResolver._normalize_text(hint)
        first = candidates[0]
        first_name = RecipientResolver._normalize_text(first.name)
        high = float(get_settings().recipient_resolver_high_confidence)
        low = float(get_settings().recipient_resolver_min_confidence)
        gap = float(get_settings().recipient_resolver_ambiguity_gap)
        if first_name == hint_text:
            return 0
        if hint_text in first_name and first.score >= 0.75:
            return 0
        if first.score >= high:
            return 0
        if len(candidates) == 1 and first.score >= low:
            return 0
        if len(candidates) > 1 and first.score >= low:
            second = candidates[1]
            if (first.score - second.score) >= gap:
                return 0
        return None

    @staticmethod
    def _extract_hint(message: str) -> str:
        # Covers forms like "给张三发", "在研发群里发", "发送消息给项目群：..."
        patterns = [
            r"(?:给|在)(?P<hint>[^，。,.\s]{1,30})(?:发|发送|说)",
            r"发送消息给(?P<hint>[^：:，。,.\s]{1,30})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return match.group("hint").strip()
        return ""

    @staticmethod
    def _score(hint: str, searchable_text: str) -> float:
        base_text = RecipientResolver._normalize_text(searchable_text)
        if not base_text:
            return 0.0
        ratio = SequenceMatcher(None, hint, base_text).ratio()
        bonus = 0.0
        if hint in base_text:
            bonus += 0.5
        if base_text.startswith(hint):
            bonus += 0.3
        return ratio + bonus

    @staticmethod
    def _normalize_text(text: str) -> str:
        raw = str(text).strip().lower()
        for source, target in RecipientResolver.TYPO_MAP.items():
            raw = raw.replace(source, target)
        return "".join(raw.split())

    @staticmethod
    def _is_generic_hint(hint: str) -> bool:
        normalized = RecipientResolver._normalize_text(hint)
        if not normalized:
            return True
        return any(key in normalized for key in RecipientResolver.GENERIC_HINTS)

    def _is_ambiguous(self, hint: str, candidates: list[RecipientCandidate]) -> bool:
        if self._is_generic_hint(hint):
            return True
        if len(candidates) < 2:
            return candidates[0].score < float(self.settings.recipient_resolver_high_confidence)
        first, second = candidates[0], candidates[1]
        gap = float(first.score) - float(second.score)
        return gap < float(self.settings.recipient_resolver_ambiguity_gap)

    def _should_try_llm_pick(
        self,
        hint: str,
        candidates: list[RecipientCandidate],
        selected_index: int | None,
        ambiguous: bool,
    ) -> bool:
        if not self.settings.recipient_resolver_use_llm:
            return False
        if not self.settings.minimax_api_key:
            return False
        if not candidates:
            return False
        if self._is_generic_hint(hint):
            return True
        if selected_index is None:
            return True
        return ambiguous

    @staticmethod
    def _mark_needs_confirmation(
        payload: dict[str, Any],
        reason: str,
        candidates: list[RecipientCandidate],
    ) -> dict[str, Any]:
        unresolved = dict(payload)
        unresolved["resolution_status"] = "needs_confirmation"
        unresolved["resolution_reason"] = reason
        unresolved["resolution_candidates"] = [
            {
                "name": item.name,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "score": round(float(item.score), 4),
            }
            for item in candidates[:3]
        ]
        return unresolved

    @staticmethod
    def _resolve_sqlite_path(raw_path: str) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
            path = project_root / path
        return str(path)

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
