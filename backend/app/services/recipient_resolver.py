"""Resolve message recipients from local SQLite directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Any

from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional dependency
    fuzz = None

from app.core.config import get_settings


@dataclass(frozen=True)
class RecipientCandidate:
    """One recipient candidate from local SQLite directory."""

    entity_type: str
    entity_id: str
    name: str
    score: float


class RecipientResolver:
    """Resolve recipient ids from the model-provided chat hint."""

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

    def __init__(self, sqlite_path: str | None = None) -> None:
        self.settings = get_settings()
        self.sqlite_path = self._resolve_sqlite_path(sqlite_path or self.settings.recipient_sqlite_path)
        self._top_k = max(1, int(self.settings.recipient_resolver_top_k))
        self._recent_hits: dict[str, dict[str, Any]] = {}

    async def resolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Fill chat_id/user_id from local directory when only hint is available."""
        chat_id = str(payload.get("chat_id", "")).strip()
        user_id = str(payload.get("user_id", "")).strip()
        if chat_id or user_id:
            resolved = dict(payload)
            resolved["resolution_status"] = "resolved"
            resolved["resolution_method"] = "provided_id"
            return resolved
        hint = str(payload.get("chat_hint", "")).strip()
        if not hint:
            return self._mark_needs_confirmation(
                payload=payload,
                reason="missing_hint",
                candidates=[],
            )
        cached = self._get_recent_hit(hint=hint, payload=payload)
        if cached is not None:
            return cached
        candidates = self._search_candidates_for_variants(hint)
        if not candidates:
            return self._mark_needs_confirmation(
                payload=payload,
                reason="no_candidate",
                candidates=[],
            )
        selected_index = self._pick_by_rules(hint, candidates)
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
        resolved["resolution_method"] = "rules"
        resolved["resolution_score"] = round(float(selected.score), 4)
        if selected.entity_type == "chat":
            resolved["chat_id"] = selected.entity_id
            resolved["user_id"] = ""
        else:
            resolved["user_id"] = selected.entity_id
            resolved["chat_id"] = ""
        self._remember_hit(hint=hint, resolved=resolved)
        return resolved

    def _get_recent_hit(self, hint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        normalized = self._normalize_text(hint)
        if not normalized:
            return None
        cached = self._recent_hits.get(normalized)
        if not cached:
            return None
        resolved = dict(payload)
        resolved.update(cached)
        resolved["resolution_method"] = "cache"
        return resolved

    def _remember_hit(self, hint: str, resolved: dict[str, Any]) -> None:
        normalized = self._normalize_text(hint)
        if not normalized:
            return
        self._recent_hits[normalized] = {
            "chat_id": str(resolved.get("chat_id", "")).strip(),
            "user_id": str(resolved.get("user_id", "")).strip(),
            "resolved_name": str(resolved.get("resolved_name", "")).strip(),
            "resolution_status": "resolved",
            "resolution_score": float(resolved.get("resolution_score", 1.0) or 1.0),
        }
        if len(self._recent_hits) > 64:
            oldest_key = next(iter(self._recent_hits))
            self._recent_hits.pop(oldest_key, None)

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

    def _search_candidates_for_variants(self, hint: str) -> list[RecipientCandidate]:
        merged: dict[str, RecipientCandidate] = {}
        for variant in self._expand_alias(hint):
            for candidate in self._search_candidates(variant):
                previous = merged.get(candidate.entity_id)
                if previous is None or candidate.score > previous.score:
                    merged[candidate.entity_id] = candidate
        ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        return ranked[: self._top_k]

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
    def _score(hint: str, searchable_text: str) -> float:
        base_text = RecipientResolver._normalize_text(searchable_text)
        if not base_text:
            return 0.0
        if fuzz is not None:
            ratio = max(
                float(fuzz.ratio(hint, base_text)) / 100.0,
                float(fuzz.partial_ratio(hint, base_text)) / 100.0,
            )
        else:
            ratio = SequenceMatcher(None, hint, base_text).ratio()
        bonus = 0.0
        if hint in base_text:
            bonus += 0.5
        if base_text.startswith(hint):
            bonus += 0.3
        return min(1.0, ratio + bonus)

    @staticmethod
    def _normalize_text(text: str) -> str:
        raw = str(text).strip().lower()
        for source, target in RecipientResolver.TYPO_MAP.items():
            raw = raw.replace(source, target)
        compact = re.sub(r"[\s_\-]+", "", raw)
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", compact)

    @staticmethod
    def _is_generic_hint(hint: str) -> bool:
        normalized = RecipientResolver._normalize_text(hint)
        if not normalized:
            return True
        return any(key in normalized for key in RecipientResolver.GENERIC_HINTS)

    @staticmethod
    def _expand_alias(hint: str) -> list[str]:
        raw_hint = str(hint).strip()
        variants: set[str] = {raw_hint}
        normalized = RecipientResolver._normalize_text(raw_hint)
        if not normalized:
            return [raw_hint]
        variants.add(normalized)
        if normalized.startswith(("小", "老", "阿")) and len(normalized) >= 2:
            variants.add(normalized[1:])
        if len(normalized) == 1:
            variants.add(f"小{normalized}")
            variants.add(f"老{normalized}")
            variants.add(f"阿{normalized}")
        return [item for item in variants if item]

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
