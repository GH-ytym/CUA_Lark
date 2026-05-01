"""Manual Qwen structured-output evaluation across multiple capabilities."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.intent_service import IntentService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Qwen structured capability parsing.")
    parser.add_argument(
        "--cases",
        default="backend/tests/fixtures/intent_qwen_structured_cases.json",
        help="JSON case file. Path is relative to project root by default.",
    )
    parser.add_argument(
        "--save-path",
        default="backend/tests/results/intent/intent_qwen_structured_result.json",
        help="JSON report output path. Path is relative to project root by default.",
    )
    parser.add_argument("--runs", type=int, default=1, help="Repeated runs per case.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout seconds per parse.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print report to stdout.")
    return parser.parse_args()


def resolve_backend_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    project_root = Path(__file__).resolve().parents[3]
    backend_root = Path(__file__).resolve().parents[2]
    project_candidate = project_root / path
    if project_candidate.exists() or str(path).startswith("backend/"):
        return project_candidate
    return backend_root / path


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


async def parse_one(service: IntentService, case: dict[str, Any], run: int, timeout: float) -> dict[str, Any]:
    message = str(case["message"])
    started = time.perf_counter()
    try:
        decision = await asyncio.wait_for(service.parse(message), timeout=max(1.0, timeout))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        payload = dict(decision.standard_action.payload)
        capability_id = decision.standard_action.capability_id.value
        expected_capability = str(case.get("expected_capability_id", ""))
        expected_payload = case.get("expected_payload", {})
        payload_checks = compare_payload(payload, expected_payload if isinstance(expected_payload, dict) else {})
        capability_match = capability_id == expected_capability
        return {
            "id": case.get("id", ""),
            "run": run,
            "message": message,
            "elapsed_ms": elapsed_ms,
            "parse_source": decision.parse_source,
            "reason": decision.reason,
            "expected_capability_id": expected_capability,
            "actual_capability_id": capability_id,
            "capability_match": capability_match,
            "expected_payload": expected_payload,
            "actual_payload": payload,
            "payload_checks": payload_checks,
            "payload_match": all(item["match"] for item in payload_checks),
            "passed": capability_match and all(item["match"] for item in payload_checks),
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "id": case.get("id", ""),
            "run": run,
            "message": message,
            "elapsed_ms": elapsed_ms,
            "parse_source": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "expected_capability_id": str(case.get("expected_capability_id", "")),
            "actual_capability_id": "unknown",
            "capability_match": False,
            "expected_payload": case.get("expected_payload", {}),
            "actual_payload": {},
            "payload_checks": [],
            "payload_match": False,
            "passed": False,
        }


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


def payload_value_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, str):
        if not expected:
            return True
        return expected in str(actual or "")
    return actual == expected


def build_report(results: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    capability_passed = sum(1 for item in results if item["capability_match"])
    elapsed_values = [float(item["elapsed_ms"]) for item in results if isinstance(item.get("elapsed_ms"), int | float)]
    by_case: dict[str, dict[str, Any]] = {}
    for item in results:
        key = str(item["id"])
        group = by_case.setdefault(key, {"runs": 0, "passed": 0, "capability_passed": 0, "elapsed_ms": []})
        group["runs"] += 1
        group["passed"] += int(bool(item["passed"]))
        group["capability_passed"] += int(bool(item["capability_match"]))
        group["elapsed_ms"].append(float(item["elapsed_ms"]))
    for group in by_case.values():
        runs = max(1, int(group["runs"]))
        group["pass_rate"] = round(group["passed"] / runs, 4)
        group["capability_pass_rate"] = round(group["capability_passed"] / runs, 4)
        case_elapsed = group.pop("elapsed_ms")
        group["average_ms"] = round(sum(case_elapsed) / max(1, len(case_elapsed)), 2)
        group["p90_ms"] = percentile(case_elapsed, 90)
    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "runs_per_case": args.runs,
            "timeout": args.timeout,
        },
        "summary": {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / max(1, total), 4),
            "capability_passed": capability_passed,
            "capability_pass_rate": round(capability_passed / max(1, total), 4),
            "average_ms": round(sum(elapsed_values) / max(1, len(elapsed_values)), 2),
            "p90_ms": percentile(elapsed_values, 90),
        },
        "by_case": by_case,
        "results": results,
    }


def percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * p / 100))
    return round(ordered[index], 2)


async def main() -> None:
    args = parse_args()
    case_path = resolve_backend_path(args.cases)
    output_path = resolve_backend_path(args.save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cases = load_cases(case_path)
    service = IntentService()
    service.settings.intent_message_fastpath_enabled = False
    service.settings.qwen_intent_timeout_seconds = int(max(1, round(args.timeout)))
    if not service.settings.dashscope_api_key:
        raise SystemExit("DASHSCOPE_API_KEY is not configured.")

    results: list[dict[str, Any]] = []
    for run in range(1, max(1, args.runs) + 1):
        for case in cases:
            one = await parse_one(service=service, case=case, run=run, timeout=args.timeout)
            results.append(one)
            status = "PASS" if one["passed"] else "FAIL"
            print(
                f"[{status}] {one['id']} | {one['actual_capability_id']} | "
                f"{one['elapsed_ms']}ms | {one['reason']}"
            )
            report = build_report(results, args)
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(results, args)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
