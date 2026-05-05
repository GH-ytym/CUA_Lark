"""Live smoke check for calendar-domain CLI create and agenda lookup.

Set FSAGENT_RUN_LIVE_CALENDAR_SMOKE=1 to create a real Feishu calendar event.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def _run(argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {argv}\nstderr: {proc.stderr}\nstdout: {proc.stdout}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json output from {argv}: {proc.stdout}") from exc


def _contains_title(payload: Any, title: str) -> bool:
    if isinstance(payload, dict):
        return any(_contains_title(value, title) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_title(value, title) for value in payload)
    return isinstance(payload, str) and title in payload


def main() -> None:
    if os.getenv("FSAGENT_RUN_LIVE_CALENDAR_SMOKE") != "1":
        print("skip: set FSAGENT_RUN_LIVE_CALENDAR_SMOKE=1 to run live calendar smoke")
        return

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    start = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    suffix = now.strftime("%Y%m%d%H%M%S")
    title = f"FSAgent-calendar-smoke-{suffix}"

    create_result = _run(
        [
            "lark-cli",
            "calendar",
            "+create",
            "--as",
            "user",
            "--summary",
            title,
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--description",
            f"calendar smoke marker: {suffix}",
        ]
    )
    agenda_result = _run(
        [
            "lark-cli",
            "calendar",
            "+agenda",
            "--as",
            "user",
            "--start",
            start.replace(hour=0, minute=0).isoformat(),
            "--end",
            start.replace(hour=23, minute=59).isoformat(),
            "--format",
            "json",
        ]
    )
    if not _contains_title(agenda_result, title):
        raise RuntimeError(f"created calendar event was not found in agenda lookup: {title}")

    print(
        json.dumps(
            {
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "create_result": create_result,
                "agenda_result": agenda_result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
