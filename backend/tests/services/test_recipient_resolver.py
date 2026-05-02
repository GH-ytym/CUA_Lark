import asyncio
from pathlib import Path
import sqlite3

from app.services.recipient_resolver import RecipientResolver


def build_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE recipients (
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                name_en TEXT NOT NULL,
                searchable_text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO recipients(entity_id, entity_type, name, name_en, searchable_text, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("ou_alice", "contact", "Alice Zhang", "Alice", "alice zhang alice", "2026-04-28"),
                ("ou_bob", "contact", "Bob Li", "Bob", "bob li bob", "2026-04-28"),
                ("ou_liuhaijun", "contact", "刘海俊", "", "刘海俊 刘海陖", "2026-04-28"),
                ("ou_wangjianguo", "contact", "王建国", "", "王建国 小王 老王 阿王", "2026-04-28"),
                ("oc_proj", "chat", "项目群", "", "项目群", "2026-04-28"),
            ],
        )
        conn.commit()


def test_resolve_contact_by_rules(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "Alice", "chat_id": "", "user_id": "", "text": "hi"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["user_id"] == "ou_alice"
    assert resolved["chat_id"] == ""
    assert resolved["resolution_status"] == "resolved"


def test_resolve_chat_by_rules_without_picker(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "项目群", "chat_id": "", "user_id": "", "text": "今晚发布"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["chat_id"] == "oc_proj"
    assert resolved["user_id"] == ""
    assert resolved["resolution_status"] == "resolved"


def test_resolve_typo_name_with_rules(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "刘海陖", "chat_id": "", "user_id": "", "text": "hi"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["user_id"] == "ou_liuhaijun"
    assert resolved["resolution_status"] == "resolved"


def test_generic_hint_needs_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "他们", "chat_id": "", "user_id": "", "text": "你好"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["chat_id"] == ""
    assert resolved["user_id"] == ""
    assert resolved["resolution_status"] == "needs_confirmation"
    assert resolved["resolution_candidates"]


def test_recent_hit_cache_shortcuts_second_lookup(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "项目群", "chat_id": "", "user_id": "", "text": "今晚发布"}

    first = asyncio.run(resolver.resolve(payload=payload))
    second = asyncio.run(resolver.resolve(payload=payload))

    assert first["chat_id"] == "oc_proj"
    assert second["chat_id"] == "oc_proj"
    assert second["resolution_method"] == "cache"


def test_alias_expand_matches_xiao_wang(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "小王", "chat_id": "", "user_id": "", "text": "你好"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["user_id"] == "ou_wangjianguo"
    assert resolved["resolution_status"] == "resolved"


def test_missing_hint_needs_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "", "chat_id": "", "user_id": "", "text": "今晚发布"}
    resolved = asyncio.run(resolver.resolve(payload=payload))
    assert resolved["resolution_status"] == "needs_confirmation"
    assert resolved["resolution_reason"] == "missing_hint"


def test_resolution_is_stable_under_repeated_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "recipients.db"
    build_db(db_path)
    resolver = RecipientResolver(sqlite_path=str(db_path))
    payload = {"chat_hint": "小王", "chat_id": "", "user_id": "", "text": "重复验证"}
    user_ids = []
    for _ in range(20):
        resolved = asyncio.run(resolver.resolve(payload=payload))
        user_ids.append(resolved.get("user_id", ""))
    assert set(user_ids) == {"ou_wangjianguo"}
