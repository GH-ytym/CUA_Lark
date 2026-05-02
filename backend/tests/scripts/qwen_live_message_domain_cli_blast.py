"""Blast-test message-domain parse and dry-run CLI execution with real Qwen."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.domain.enums import CapabilityId
from app.services.intent_service import IntentService
from app.services.lark_cli_service import LarkCliService
from app.services.recipient_resolver import RecipientResolver


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run message-domain live blast tests with real Qwen.")
    parser.add_argument(
        "--cases",
        default="tests/fixtures/message_domain_blast_cases.json",
        help="JSON case file path.",
    )
    parser.add_argument("--runs", type=int, default=3, help="Runs per case.")
    parser.add_argument(
        "--save-path",
        default="tests/results/intent/message_domain_blast_live.json",
        help="Output report path.",
    )
    return parser.parse_args()


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / path


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
                ("oc_release", "chat", "发布小组", "", "发布小组 发布同步群 小组", "2026-05-01"),
                ("ou_mei", "contact", "梅家济", "Mei Jiaji", "梅家济 mei jiaji", "2026-05-01"),
            ],
        )
        conn.commit()


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def payload_value_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, str):
        return expected in str(actual or "")
    return actual == expected


def compare_payload(actual: dict[str, object], expected: dict[str, object]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        checks.append(
            {
                "field": key,
                "expected": expected_value,
                "actual": actual_value,
                "match": payload_value_matches(actual_value, expected_value),
            }
        )
    return checks


def can_dry_run_cli(capability_id: str, payload: dict[str, object], missing_fields: list[str]) -> bool:
    if missing_fields:
        return False
    if capability_id == CapabilityId.IM_MESSAGE_SEND.value:
        return bool(str(payload.get("chat_id", "")).strip() or str(payload.get("user_id", "")).strip())
    if capability_id == CapabilityId.IM_MESSAGES_SEARCH.value:
        return bool(str(payload.get("chat_id", "")).strip() and str(payload.get("query", "")).strip())
    if capability_id == CapabilityId.IM_CHAT_MESSAGES_LIST.value:
        return bool(str(payload.get("chat_id", "")).strip() or str(payload.get("user_id", "")).strip())
    if capability_id == CapabilityId.IM_CHAT_SEARCH.value:
        return bool(str(payload.get("query", "")).strip())
    if capability_id == CapabilityId.IM_CHAT_CREATE.value:
        return bool(str(payload.get("name", "")).strip())
    return False


async def run_case(
    intent_service: IntentService,
    cli_service: LarkCliService,
    case: dict[str, Any],
    run_index: int,
) -> dict[str, Any]:
    message = str(case["message"])
    started = time.perf_counter()
    decision = await intent_service.parse(message)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    payload = dict(decision.standard_action.payload)
    payload_checks = compare_payload(payload, dict(case.get("expected_payload", {})))
    capability_match = decision.standard_action.capability_id.value == str(case.get("expected_capability_id", ""))
    payload_match = all(item["match"] for item in payload_checks)

    cli_attempted = False
    cli_success = False
    cli_summary = ""
    cli_command = ""
    if can_dry_run_cli(decision.standard_action.capability_id.value, payload, list(decision.missing_fields)):
        cli_attempted = True
        cli_result = cli_service.execute_action(
            action=decision.standard_action.model_copy(update={"payload": payload | {"dry_run": True}}),
            dry_run=True,
        )
        cli_success = cli_result.success
        cli_summary = cli_result.summary
        steps = cli_result.payload.get("steps", [])
        if isinstance(steps, list) and steps:
            cli_command = str(steps[0].get("command", ""))

    return {
        "id": str(case.get("id", "")),
        "run": run_index,
        "message": message,
        "elapsed_ms": elapsed_ms,
        "parse_source": decision.parse_source,
        "capability_id": decision.standard_action.capability_id.value,
        "reason": decision.reason,
        "missing_fields": list(decision.missing_fields),
        "payload": payload,
        "payload_checks": payload_checks,
        "capability_match": capability_match,
        "payload_match": payload_match,
        "passed": capability_match and payload_match,
        "cli_attempted": cli_attempted,
        "cli_success": cli_success,
        "cli_summary": cli_summary,
        "cli_command": cli_command,
    }


def build_report(results: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    by_case: dict[str, dict[str, Any]] = {}
    for item in results:
        case_id = str(item["id"])
        group = by_case.setdefault(
            case_id,
            {
                "runs": 0,
                "passed": 0,
                "cli_attempted": 0,
                "cli_success": 0,
                "average_ms_values": [],
                "parse_source_count": {},
            },
        )
        group["runs"] += 1
        group["passed"] += int(bool(item["passed"]))
        group["cli_attempted"] += int(bool(item["cli_attempted"]))
        group["cli_success"] += int(bool(item["cli_success"]))
        group["average_ms_values"].append(float(item["elapsed_ms"]))
        source = str(item["parse_source"])
        group["parse_source_count"][source] = int(group["parse_source_count"].get(source, 0)) + 1
    for group in by_case.values():
        values = group.pop("average_ms_values")
        group["pass_rate"] = round(group["passed"] / max(1, group["runs"]), 4)
        group["cli_success_rate"] = round(group["cli_success"] / max(1, group["cli_attempted"]), 4) if group["cli_attempted"] else 0.0
        group["average_ms"] = round(sum(values) / max(1, len(values)), 2)

    total = len(results)
    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "runs_per_case": runs,
        "total_results": total,
        "overall_passed": sum(1 for item in results if item["passed"]),
        "overall_pass_rate": round(sum(1 for item in results if item["passed"]) / max(1, total), 4),
        "cli_attempted": sum(1 for item in results if item["cli_attempted"]),
        "cli_success": sum(1 for item in results if item["cli_success"]),
        "cli_success_rate": round(
            sum(1 for item in results if item["cli_success"]) / max(1, sum(1 for item in results if item["cli_attempted"])),
            4,
        )
        if any(item["cli_attempted"] for item in results)
        else 0.0,
        "by_case": by_case,
        "results": results,
    }


async def main() -> None:
    args = parse_args()
    cases = load_cases(resolve_path(args.cases))
    save_path = resolve_path(args.save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fsagent_msg_blast_") as tmp_dir:
        db_path = Path(tmp_dir) / "recipients.db"
        build_db(db_path)

        intent_service = IntentService()
        intent_service.settings.intent_require_llm = True
        intent_service.recipient_resolver = RecipientResolver(sqlite_path=str(db_path))
        cli_service = LarkCliService()

        results: list[dict[str, Any]] = []
        for run_index in range(1, max(1, args.runs) + 1):
            for case in cases:
                one = await run_case(intent_service=intent_service, cli_service=cli_service, case=case, run_index=run_index)
                results.append(one)
                print(
                    f"[run {run_index}] {one['id']} | {one['capability_id']} | "
                    f"pass={one['passed']} | cli={one['cli_success']} | {one['elapsed_ms']}ms"
                )

        report = build_report(results=results, runs=args.runs)
        save_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
