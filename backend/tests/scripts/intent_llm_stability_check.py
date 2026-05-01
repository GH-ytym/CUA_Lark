"""Manual stability check for IntentService with real Qwen calls."""

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
    parser = argparse.ArgumentParser(description="Run repeated IntentService checks with real LLM calls.")
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Input message to test. Repeat this flag to provide multiple messages.",
    )
    parser.add_argument(
        "--message-file",
        default="",
        help="Optional text file path with one message per line.",
    )
    parser.add_argument("--runs", type=int, default=10, help="How many repeated runs to execute.")
    parser.add_argument(
        "--runs-per-message",
        type=int,
        default=0,
        help="If >0, total runs becomes len(messages) * runs-per-message.",
    )
    parser.add_argument(
        "--per-run-timeout",
        type=float,
        default=25.0,
        help="Timeout (seconds) for each single parse run.",
    )
    parser.add_argument(
        "--save-path",
        default="backend/tests/results/intent/intent_llm_stability_result.json",
        help="JSON output path. The report is updated after each run.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable per-run progress logs.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON result for easier inspection.",
    )
    return parser.parse_args()


async def run_once(service: IntentService, message: str, index: int) -> dict[str, Any]:
    started = time.perf_counter()
    decision = await service.parse(message)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    payload = decision.structured_command.get("payload", {}) if isinstance(decision.structured_command, dict) else {}
    resolution_status = payload.get("resolution_status", "unknown") if isinstance(payload, dict) else "unknown"
    return {
        "run": index,
        "message": message,
        "elapsed_ms": elapsed_ms,
        "parse_source": decision.parse_source,
        "intent_type": decision.intent_type.value,
        "capability_id": decision.standard_action.capability_id.value,
        "reason": decision.reason,
        "missing_fields": list(decision.missing_fields),
        "resolution_status": resolution_status,
        "raw_llm_payload": dict(decision.raw_llm_payload),
        "final_payload": payload,
    }


def to_output_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[3]
        backend_root = Path(__file__).resolve().parents[2]
        project_candidate = project_root / path
        path = project_candidate if project_candidate.exists() or str(path).startswith("backend/") else backend_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_report(
    results: list[dict[str, Any]],
    runtime_config: dict[str, Any],
) -> dict[str, Any]:
    success_count = sum(1 for item in results if item["capability_id"] == "im.message_send")
    resolved_count = sum(
        1
        for item in results
        if isinstance(item.get("final_payload"), dict)
        and (item["final_payload"].get("user_id") or item["final_payload"].get("chat_id"))
    )
    parse_source_count: dict[str, int] = {}
    resolution_status_count: dict[str, int] = {}
    for item in results:
        source = str(item.get("parse_source", "unknown"))
        parse_source_count[source] = parse_source_count.get(source, 0) + 1
        status = str(item.get("resolution_status", "unknown"))
        resolution_status_count[status] = resolution_status_count.get(status, 0) + 1
    per_message: dict[str, dict[str, Any]] = {}
    for item in results:
        key = str(item.get("message", ""))
        group = per_message.setdefault(
            key,
            {"runs": 0, "message_send_count": 0, "resolved_target_count": 0},
        )
        group["runs"] += 1
        if item.get("capability_id") == "im.message_send":
            group["message_send_count"] += 1
        payload = item.get("final_payload", {})
        if isinstance(payload, dict) and (payload.get("user_id") or payload.get("chat_id")):
            group["resolved_target_count"] += 1
        status = str(item.get("resolution_status", "unknown"))
        status_key = f"resolution_{status}_count"
        group[status_key] = int(group.get(status_key, 0)) + 1
    for group in per_message.values():
        runs = max(1, int(group["runs"]))
        group["message_send_rate"] = round(group["message_send_count"] / runs, 4)
        group["resolved_target_rate"] = round(group["resolved_target_count"] / runs, 4)

    return {
        "runtime_config": runtime_config,
        "messages": sorted(per_message.keys()),
        "runs": len(results),
        "message_send_count": success_count,
        "message_send_rate": round(success_count / max(1, len(results)), 4),
        "resolved_target_count": resolved_count,
        "resolved_target_rate": round(resolved_count / max(1, len(results)), 4),
        "parse_source_count": parse_source_count,
        "resolution_status_count": resolution_status_count,
        "per_message": per_message,
        "updated_at": datetime.now(UTC).isoformat(),
        "results": results,
    }


def dump_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    args = parse_args()
    service = IntentService()
    runtime_config = apply_runtime_mode(service=service, args=args)
    results: list[dict[str, Any]] = []
    output_path = to_output_path(args.save_path)
    messages = load_messages(args)
    total_runs = max(1, args.runs)
    if args.runs_per_message > 0:
        total_runs = max(1, len(messages) * args.runs_per_message)

    for index in range(1, total_runs + 1):
        message = messages[(index - 1) % len(messages)]
        try:
            one = await asyncio.wait_for(
                run_once(service=service, message=message, index=index),
                timeout=max(1.0, args.per_run_timeout),
            )
        except asyncio.TimeoutError:
            one = {
                "run": index,
                "message": message,
                "elapsed_ms": round(max(1.0, args.per_run_timeout) * 1000, 2),
                "parse_source": "timeout",
                "intent_type": "unknown",
                "reason": f"single run timeout: {args.per_run_timeout}s",
                "resolution_status": "timeout",
                "payload": {},
            }
        except asyncio.CancelledError:
            one = {
                "run": index,
                "message": message,
                "elapsed_ms": round(max(1.0, args.per_run_timeout) * 1000, 2),
                "parse_source": "timeout_cancelled",
                "intent_type": "unknown",
                "reason": f"single run cancelled after timeout boundary: {args.per_run_timeout}s",
                "resolution_status": "timeout",
                "payload": {},
            }
        except Exception as exc:
            one = {
                "run": index,
                "message": message,
                "elapsed_ms": 0.0,
                "parse_source": "error",
                "intent_type": "unknown",
                "reason": f"{type(exc).__name__}: {exc}",
                "resolution_status": "error",
                "payload": {},
            }

        results.append(one)
        report = build_report(results=results, runtime_config=runtime_config)
        dump_report(report=report, output_path=output_path)
        if not args.quiet:
            print(
                f"[{index}/{total_runs}] {one['parse_source']} | {one['message']} | "
                f"{one['intent_type']} | {one['resolution_status']} | {one['elapsed_ms']}ms"
            )

    report = build_report(results=results, runtime_config=runtime_config)
    dump_report(report=report, output_path=output_path)

    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))


def load_messages(args: argparse.Namespace) -> list[str]:
    messages = [str(item).strip() for item in args.message if str(item).strip()]
    if args.message_file:
        file_path = Path(args.message_file)
        if not file_path.is_absolute():
            project_root = Path(__file__).resolve().parents[3]
            backend_root = Path(__file__).resolve().parents[2]
            project_candidate = project_root / file_path
            file_path = project_candidate if project_candidate.exists() or str(file_path).startswith("backend/") else backend_root / file_path
        if file_path.exists():
            for line in file_path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if text and not text.startswith("#"):
                    messages.append(text)
    if messages:
        return messages
    return ["跟梅家济说hello"]


def apply_runtime_mode(service: IntentService, args: argparse.Namespace) -> dict[str, Any]:
    service.settings.intent_require_llm = True
    return {
        "intent_require_llm": bool(service.settings.intent_require_llm),
        "qwen_configured": bool(service.settings.dashscope_api_key),
        "qwen_model": service.settings.qwen_model,
    }


if __name__ == "__main__":
    asyncio.run(main())
