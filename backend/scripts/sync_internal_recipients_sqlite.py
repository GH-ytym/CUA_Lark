"""Scan internal contacts/chats via lark-cli and store into SQLite."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


CLI_BIN = ""


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Sync internal contacts and chats to sqlite.")
    parser.add_argument(
        "--db-path",
        default="",
        help="SQLite output path. Defaults to settings.recipient_sqlite_path.",
    )
    return parser


def run_cli_json(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, check=False, capture_output=True, text=False)
    stdout = decode_output(proc.stdout).strip()
    stderr = decode_output(proc.stderr).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{stderr or stdout}")
    text = stdout
    data = extract_json_object(text)
    if not isinstance(data, dict):
        raise RuntimeError(f"cannot parse json output: {' '.join(command)}")
    is_ok = bool(data.get("ok", False))
    if "code" in data and data.get("code") == 0:
        is_ok = True
    if not is_ok:
        raise RuntimeError(f"lark-cli call failed: {json.dumps(data, ensure_ascii=False)}")
    return data


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def normalize_text(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def decode_output(content: bytes | str | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def fetch_contacts() -> list[tuple[str, str, str, str, str, str]]:
    records: list[tuple[str, str, str, str, str, str]] = []
    page_token = ""
    now = datetime.now(UTC).isoformat()
    for _ in range(50):
        command = [
            CLI_BIN,
            "contact",
            "+search-user",
            "--query",
            " ",
            "--page-size",
            "200",
            "--format",
            "json",
        ]
        if page_token:
            command.extend(["--page-token", page_token])
        result = run_cli_json(command)
        data = result.get("data", {})
        users = data.get("users", []) if isinstance(data, dict) else []
        for item in users:
            if not isinstance(item, dict):
                continue
            open_id = str(item.get("open_id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not open_id or not name:
                continue
            name_en = str(item.get("en_name", "")).strip()
            searchable_text = normalize_text(f"{name} {name_en}")
            records.append(("contact", open_id, name, name_en, searchable_text, now))
        has_more = bool(data.get("has_more", False)) if isinstance(data, dict) else False
        page_token = str(data.get("page_token", "")).strip() if isinstance(data, dict) else ""
        if not has_more or not page_token:
            break
    return records


def fetch_chats() -> list[tuple[str, str, str, str, str, str]]:
    records: list[tuple[str, str, str, str, str, str]] = []
    now = datetime.now(UTC).isoformat()
    result = run_cli_json(
        [
            CLI_BIN,
            "im",
            "chats",
            "list",
            "--as",
            "user",
            "--page-all",
            "--page-limit",
            "50",
            "--format",
            "json",
        ]
    )
    data = result.get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if bool(item.get("external", False)):
            # Only keep internal chats.
            continue
        chat_id = str(item.get("chat_id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not chat_id or not name:
            continue
        searchable_text = normalize_text(name)
        records.append(("chat", chat_id, name, "", searchable_text, now))
    return records


def write_sqlite(db_path: Path, records: list[tuple[str, str, str, str, str, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recipients (
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('contact','chat')),
                name TEXT NOT NULL,
                name_en TEXT NOT NULL,
                searchable_text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recipients_type_name ON recipients(entity_type, name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recipients_search ON recipients(searchable_text)")
        conn.execute("DELETE FROM recipients WHERE entity_type IN ('contact', 'chat')")
        conn.executemany(
            """
            INSERT INTO recipients (entity_type, entity_id, name, name_en, searchable_text, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type=excluded.entity_type,
                name=excluded.name,
                name_en=excluded.name_en,
                searchable_text=excluded.searchable_text,
                updated_at=excluded.updated_at
            """,
            records,
        )
        conn.commit()


def resolve_db_path(cli_path: str) -> Path:
    if cli_path:
        path = Path(cli_path)
    else:
        settings = get_settings()
        path = Path(settings.recipient_sqlite_path)
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[2]
        path = project_root / path
    return path


def resolve_cli_bin() -> str:
    settings = get_settings()
    configured = (settings.lark_cli_path or "").strip() or "lark-cli"
    if Path(configured).is_file():
        return configured
    which_path = shutil.which(configured)
    if which_path:
        return which_path
    cmd_path = shutil.which(f"{configured}.cmd")
    if cmd_path:
        return cmd_path
    if Path("C:/Users/HP/AppData/Roaming/npm/lark-cli.cmd").exists():
        return "C:/Users/HP/AppData/Roaming/npm/lark-cli.cmd"
    return configured


def main() -> None:
    global CLI_BIN
    args = parse_args().parse_args()
    CLI_BIN = resolve_cli_bin()
    db_path = resolve_db_path(args.db_path)
    contacts = fetch_contacts()
    chats = fetch_chats()
    all_records = contacts + chats
    write_sqlite(db_path=db_path, records=all_records)
    summary = {
        "db_path": str(db_path),
        "contacts": len(contacts),
        "chats": len(chats),
        "total": len(all_records),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
