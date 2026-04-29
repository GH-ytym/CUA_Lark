"""Day4 message-domain smoke test for CLI real chain and command comparison."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.enums import IntentType
from app.integrations.lark_cli_adapter import CliInvocation, LarkCliAdapter
from app.services.intent_service import IntentService
from app.services.lark_cli_service import LarkCliService


@dataclass(frozen=True)
class MessageSmokeCase:
    message: str
    expected_payload: dict[str, str]
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run day4 message smoke with local DB-backed recipients.")
    parser.add_argument(
        "--db-path",
        default="data/lark_recipients.db",
        help="SQLite path of recipients db.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="How many rounds to run for each case.",
    )
    parser.add_argument(
        "--report-path",
        default="docs/day4-message-smoke-report.md",
        help="Output markdown report path.",
    )
    return parser.parse_args()


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def load_cases(db_path: Path) -> list[MessageSmokeCase]:
    if not db_path.exists():
        raise FileNotFoundError(f"recipient db not found: {db_path}")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT entity_type, entity_id, name
            FROM recipients
            WHERE name IS NOT NULL AND name != ''
            """
        ).fetchall()
    contacts = [(row[1], row[2]) for row in rows if row[0] == "contact"]
    chats = [(row[1], row[2]) for row in rows if row[0] == "chat"]
    if len(contacts) < 2:
        raise RuntimeError("need at least 2 contacts in recipients db")
    if not chats:
        raise RuntimeError("need at least 1 chat in recipients db")
    user1_id, user1_name = contacts[0]
    user2_id, user2_name = contacts[1]
    chat_id, chat_name = chats[0]
    return [
        MessageSmokeCase(
            message=f"给{user1_name}发送：今天18:00前提交周报。",
            expected_payload={"chat_id": "", "user_id": user1_id, "text": "今天18:00前提交周报。", "identity": "bot"},
            note="单聊明确姓名",
        ),
        MessageSmokeCase(
            message=f'给{user2_name}说："请确认明天评审材料"',
            expected_payload={"chat_id": "", "user_id": user2_id, "text": "请确认明天评审材料", "identity": "bot"},
            note="单聊引号正文",
        ),
        MessageSmokeCase(
            message=f"请帮我在{chat_name}里发：CI 已恢复，大家可以继续合并。",
            expected_payload={"chat_id": chat_id, "user_id": "", "text": "CI 已恢复，大家可以继续合并。", "identity": "bot"},
            note="群聊口语化",
        ),
        MessageSmokeCase(
            message=f"发送消息给{chat_name}：今晚 9 点发布，注意回归验证。",
            expected_payload={"chat_id": chat_id, "user_id": "", "text": "今晚 9 点发布，注意回归验证。", "identity": "bot"},
            note="群聊倒装句",
        ),
    ]


def _payload_from_structured(structured: dict[str, Any]) -> dict[str, str]:
    payload = structured.get("payload", {}) if isinstance(structured, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "chat_id": str(payload.get("chat_id", "")).strip(),
        "user_id": str(payload.get("user_id", "")).strip(),
        "text": str(payload.get("text", payload.get("message", ""))).strip(),
        "identity": str(payload.get("identity", "bot")).strip() or "bot",
    }


def _build_command_or_error(adapter: LarkCliAdapter, payload: dict[str, str]) -> tuple[str, str]:
    invocation = CliInvocation(tool_family="lark-im", operation="message_send", arguments=payload)
    try:
        argv = adapter.build_command(invocation=invocation, cli_bin="lark-cli", dry_run=True)
        return adapter.stringify_command(argv), ""
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)


async def run(rounds: int, db_path: Path, report_path: Path) -> Path:
    adapter = LarkCliAdapter()
    intent_service = IntentService()
    cli_service = LarkCliService(adapter=adapter)
    cases = load_cases(db_path)
    rounds = max(1, int(rounds))
    now = datetime.now(UTC).isoformat()
    total_runs = rounds * len(cases)
    passed_execution = 0
    matched_command = 0
    rows: list[str] = [
        "# Day4 消息域真实链路冒烟测试",
        "",
        f"- 生成时间（UTC）：`{now}`",
        f"- 收件人库：`{db_path}`",
        f"- 测试轮次：`{rounds}`（总用例执行 `{total_runs}` 次）",
        "- 说明：执行链路走 `LarkCliService.execute`，并统一使用 `--dry-run` 防止真实发消息。",
        "",
        "| 轮次 | 编号 | 自然语言消息 | 理论 CLI 真实命令（dry-run） | MiniMax/规则结构化命令 | 结构化命令生成 CLI | 对比结论 | 执行结果 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for round_idx in range(1, rounds + 1):
        for idx, case in enumerate(cases, start=1):
            decision = await intent_service.parse(message=case.message)
            structured = decision.structured_command
            structured_payload = _payload_from_structured(structured)

            theoretical_cmd, theoretical_err = _build_command_or_error(adapter, case.expected_payload)
            structured_cmd, structured_err = _build_command_or_error(adapter, structured_payload)

            if theoretical_err:
                compare = f"理论命令构建失败：{theoretical_err}"
            elif structured_err:
                compare = f"不一致（结构化命令缺参：{structured_err}）"
            elif structured_cmd == theoretical_cmd:
                compare = "一致"
            else:
                compare = "不一致（字段抽取差异）"

            execute_payload = dict(structured_payload)
            execution = cli_service.execute(intent=IntentType.MESSAGE_SEND, payload=execute_payload, dry_run=True)
            if execution.success:
                passed_execution += 1
            if compare == "一致":
                matched_command += 1
            exec_brief = f"success={execution.success}"
            if execution.payload.get("steps"):
                first_step = execution.payload["steps"][0]
                exec_brief = (
                    f"success={execution.success}, exit={first_step.get('exit_code')}, "
                    f"cost={first_step.get('duration_ms')}ms"
                )
            if not execution.success and execution.error_code is not None:
                exec_brief = f"{exec_brief}, code={execution.error_code.value}, reason={execution.summary}"

            structured_text = json.dumps(
                {
                    "parse_source": decision.parse_source,
                    "intent_type": decision.intent_type.value,
                    "payload": structured_payload,
                    "note": case.note,
                },
                ensure_ascii=False,
            )
            rows.append(
                "| "
                + " | ".join(
                    [
                        str(round_idx),
                        str(idx),
                        case.message.replace("|", "/"),
                        (theoretical_cmd or theoretical_err).replace("|", "/"),
                        structured_text.replace("|", "/"),
                        (structured_cmd or structured_err).replace("|", "/"),
                        compare.replace("|", "/"),
                        exec_brief.replace("|", "/"),
                    ]
                )
                + " |"
            )
    rows.extend(
        [
            "",
            "## 汇总",
            "",
            f"- 命令构建一致率：`{matched_command}/{total_runs}`",
            f"- 执行成功率：`{passed_execution}/{total_runs}`",
        ]
    )
    report_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report_path


if __name__ == "__main__":
    args = parse_args()
    output = asyncio.run(
        run(
            rounds=args.rounds,
            db_path=_resolve_path(args.db_path),
            report_path=_resolve_path(args.report_path),
        )
    )
    print(output)
