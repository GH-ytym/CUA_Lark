"""Live smoke check for docs-domain CLI create/search/update/fetch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
import subprocess
from typing import Any


def _run(argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {argv}\nstderr: {proc.stderr}\nstdout: {proc.stdout}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid json output from {argv}: {proc.stdout}") from exc


def _extract_doc_token(payload: dict[str, Any]) -> str:
    document = payload.get("document")
    if isinstance(document, dict):
        for key in ("document_id", "document_token", "token"):
            value = str(document.get(key, "")).strip()
            if value:
                return value
    data = payload.get("data")
    if isinstance(data, dict):
        document = data.get("document")
        if isinstance(document, dict):
            for key in ("document_id", "document_token", "token"):
                value = str(document.get(key, "")).strip()
                if value:
                    return value
    raise RuntimeError(f"could not extract document token from: {payload}")


def main() -> None:
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    title = f"FSAgent-docs-smoke-{suffix}"
    initial_markdown = f"# {title}\n\ncreate marker: {suffix}"
    appended_markdown = f"\n\nappend marker: {suffix}"

    create_result = _run(
        [
            "lark-cli",
            "docs",
            "+create",
            "--as",
            "user",
            "--title",
            title,
            "--markdown",
            initial_markdown,
        ]
    )
    doc_token = _extract_doc_token(create_result)

    search_result = _run(
        [
            "lark-cli",
            "docs",
            "+search",
            "--as",
            "user",
            "--query",
            title,
        ]
    )

    update_result = _run(
        [
            "lark-cli",
            "docs",
            "+update",
            "--as",
            "user",
            "--doc",
            doc_token,
            "--mode",
            "append",
            "--markdown",
            appended_markdown,
        ]
    )

    fetch_result = _run(
        [
            "lark-cli",
            "docs",
            "+fetch",
            "--as",
            "user",
            "--doc",
            doc_token,
        ]
    )

    print(
        json.dumps(
            {
                "title": title,
                "doc_token": doc_token,
                "create_result": create_result,
                "search_result": search_result,
                "update_result": update_result,
                "fetch_result": fetch_result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
