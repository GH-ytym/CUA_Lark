"""Live smoke check for message-domain Qwen parse -> resolver -> CLI dry-run."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.intent_service import IntentService
from app.services.lark_cli_service import LarkCliService
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
                ("oc_proj", "chat", "项目群", "", "项目群 项目组 发布群", "2026-05-01"),
                ("ou_demo", "contact", "梅家济", "Mei Jiaji", "梅家济 mei jiaji", "2026-05-01"),
            ],
        )
        conn.commit()


async def main() -> None:
    db_path = Path(__file__).resolve().parent / "tmp_live_recipients.db"
    if db_path.exists():
        db_path.unlink()
    build_db(db_path)

    intent_service = IntentService()
    intent_service.settings.intent_require_llm = True
    intent_service.recipient_resolver = RecipientResolver(sqlite_path=str(db_path))

    cli_service = LarkCliService()
    cases = [
        "跟项目群说今晚九点发布，注意回归验证。",
        "搜索项目群里关于发布的消息",
    ]
    output: list[dict[str, object]] = []
    for message in cases:
        decision = await intent_service.parse(message)
        cli_result = cli_service.execute_action(
            action=decision.standard_action.model_copy(
                update={"payload": dict(decision.standard_action.payload) | {"dry_run": True}}
            ),
            dry_run=True,
        )
        output.append(
            {
                "message": message,
                "parse_source": decision.parse_source,
                "capability_id": decision.standard_action.capability_id.value,
                "missing_fields": decision.missing_fields,
                "payload": dict(decision.standard_action.payload),
                "cli_success": cli_result.success,
                "cli_status": cli_result.status.value,
                "cli_summary": cli_result.summary,
                "cli_payload": cli_result.payload,
            }
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
