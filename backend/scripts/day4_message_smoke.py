"""Day4 message-domain smoke test for CLI real chain and command comparison."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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


CASES: list[MessageSmokeCase] = [
    MessageSmokeCase(
        message="给产品群发一条消息：今天18:00前提交周报。",
        expected_payload={"chat_id": "oc_demo_product", "user_id": "", "text": "今天18:00前提交周报。", "identity": "bot"},
        note="群消息",
    ),
    MessageSmokeCase(
        message='给ou_demo_alice发送："请确认明天评审材料"',
        expected_payload={"chat_id": "", "user_id": "ou_demo_alice", "text": "请确认明天评审材料", "identity": "bot"},
        note="单聊 open_id",
    ),
    MessageSmokeCase(
        message="请帮我在研发群里发：CI 已恢复，大家可以继续合并。",
        expected_payload={"chat_id": "oc_demo_rd", "user_id": "", "text": "CI 已恢复，大家可以继续合并。", "identity": "bot"},
        note="口语化描述",
    ),
    MessageSmokeCase(
        message="发送消息给项目群：今晚 9 点发布，注意回归验证。",
        expected_payload={"chat_id": "oc_demo_project", "user_id": "", "text": "今晚 9 点发布，注意回归验证。", "identity": "bot"},
        note="倒装句式",
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


async def run() -> Path:
    adapter = LarkCliAdapter()
    intent_service = IntentService()
    cli_service = LarkCliService(adapter=adapter)
    now = datetime.now(UTC).isoformat()
    rows: list[str] = [
        "# Day4 消息域真实链路冒烟测试",
        "",
        f"- 生成时间（UTC）：`{now}`",
        "- 说明：执行链路走 `LarkCliService.execute`，并统一使用 `--dry-run` 防止真实发消息。",
        "",
        "| 编号 | 自然语言消息 | 理论 CLI 真实命令（dry-run） | MiniMax/规则结构化命令 | 结构化命令生成 CLI | 对比结论 | 执行结果 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for idx, case in enumerate(CASES, start=1):
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
        if not execute_payload["chat_id"] and not execute_payload["user_id"]:
            execute_payload["chat_id"] = case.expected_payload["chat_id"]
            execute_payload["user_id"] = case.expected_payload["user_id"]
        if not execute_payload["text"]:
            execute_payload["text"] = case.expected_payload["text"]
        execution = cli_service.execute(intent=IntentType.MESSAGE_SEND, payload=execute_payload, dry_run=True)
        exec_brief = f"success={execution.success}"
        if execution.payload.get("steps"):
            first_step = execution.payload["steps"][0]
            exec_brief = (
                f"success={execution.success}, exit={first_step.get('exit_code')}, "
                f"cost={first_step.get('duration_ms')}ms"
            )
        if not execution.success and execution.error_code is not None:
            exec_brief = f"{exec_brief}, code={execution.error_code.value}"

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
    report_path = Path(__file__).resolve().parents[2] / "docs" / "day4-message-smoke-report.md"
    report_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report_path


if __name__ == "__main__":
    output = asyncio.run(run())
    print(output)
