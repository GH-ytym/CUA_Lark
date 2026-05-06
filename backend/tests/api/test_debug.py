from pathlib import Path
import subprocess

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import httpx

from app.main import create_app


def test_enable_lark_cli_updates_env_in_tmp_project(monkeypatch, tmp_path) -> None:
    cli_bin = tmp_path / "bin" / "lark-cli"
    cli_bin.parent.mkdir()
    cli_bin.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    cli_bin.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/lark-cli/enable",
        json={"path": str(cli_bin), "workdir": "runtime/lark-cli"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["bin_path"] == str(cli_bin)
    assert set(data["updated_keys"]) == {"LARK_CLI_PATH", "LARK_CLI_WORKDIR"}
    env_values = dotenv_values(Path(".env"))
    assert env_values["LARK_CLI_PATH"] == str(cli_bin)
    assert env_values["LARK_CLI_WORKDIR"] == str((tmp_path / "runtime" / "lark-cli").resolve())
    assert data["detail"]["ready"] is False


def test_install_lark_cli_uses_local_npm_prefix_and_enables_bin(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    fake_npm = tmp_path / "npm"
    fake_npm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_npm.chmod(0o755)
    captured: dict[str, object] = {}

    def fake_which(command: str) -> str | None:
        if command == "npm":
            return str(fake_npm)
        if command == "node":
            return "/usr/bin/node"
        return None

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:2] == [str(fake_npm), "install"]:
            captured["command"] = command
            captured["cwd"] = kwargs["cwd"]
            cwd = Path(str(kwargs["cwd"]))
            bin_path = cwd / "node_modules" / ".bin" / "lark-cli"
            bin_path.parent.mkdir(parents=True)
            bin_path.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="installed", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="not configured")

    from app.api.routes import debug

    monkeypatch.setattr(debug.shutil, "which", fake_which)
    monkeypatch.setattr(debug.subprocess, "run", fake_run)

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/lark-cli/install",
        json={"package_name": "@larksuite/cli", "registry_url": ""},
    )

    assert response.status_code == 200
    data = response.json()
    install_dir = tmp_path / "runtime" / "lark-cli"
    assert captured["command"] == [str(fake_npm), "install", "@larksuite/cli", "--save-exact"]
    assert captured["cwd"] == install_dir.resolve()
    assert data["bin_path"] == str((install_dir / "node_modules" / ".bin" / "lark-cli").resolve())
    assert data["stdout"] == "installed"
    assert set(data["updated_keys"]) == {"LARK_CLI_PATH", "LARK_CLI_WORKDIR"}


def test_install_lark_cli_rejects_unsafe_package_name(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())
    response = client.post(
        "/api/debug/lark-cli/install",
        json={"package_name": "@larksuite/cli; rm -rf /", "registry_url": ""},
    )

    assert response.status_code == 400
    assert "包名格式不合法" in response.json()["detail"]


def test_probe_qwen_models_uses_chat_url_and_selects_available_model(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    class FakeAsyncClient:
        def __init__(self, timeout: int) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(
                200,
                json={"data": [{"id": "qwen-plus"}, {"id": "qwen-max"}, {"id": "qwen-plus"}]},
            )

    from app.api.routes import debug

    monkeypatch.setattr(debug.httpx, "AsyncClient", FakeAsyncClient)

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/qwen/models",
        json={
            "dashscope_api_key": "sk-test",
            "qwen_chat_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "qwen_model": "qwen-max",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert data["models"] == ["qwen-plus", "qwen-max"]
    assert data["selected_model"] == "qwen-max"
    assert data["selected_available"] is True


def test_probe_qwen_models_reports_bad_key(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    class FakeAsyncClient:
        def __init__(self, timeout: int) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]):
            return httpx.Response(401, json={"error": "unauthorized"})

    from app.api.routes import debug

    monkeypatch.setattr(debug.httpx, "AsyncClient", FakeAsyncClient)

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/qwen/models",
        json={
            "dashscope_api_key": "bad-key",
            "qwen_chat_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "qwen_model": "",
        },
    )

    assert response.status_code == 400
    assert "API Key 校验失败" in response.json()["detail"]


def test_lark_cli_account_reports_config_and_auth(monkeypatch, tmp_path) -> None:
    cli_bin = tmp_path / "lark-cli"
    cli_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    cli_bin.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    def fake_resolve_lark_cli_path(_: str) -> Path:
        return cli_bin

    def fake_run_cli_quick(command: list[str], cwd: str | None = None) -> dict[str, object]:
        if command[1:3] == ["config", "show"]:
            return {"returncode": 0, "stdout": '{"appId":"cli_app"}', "stderr": ""}
        if command[1:3] == ["auth", "status"]:
            return {"returncode": 0, "stdout": '{"user":{"email":"me@example.com"}}', "stderr": ""}
        if command[1:3] == ["auth", "list"]:
            return {"returncode": 0, "stdout": "[]", "stderr": ""}
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    from app.api.routes import debug

    monkeypatch.setattr(debug, "_resolve_lark_cli_path", fake_resolve_lark_cli_path)
    monkeypatch.setattr(debug, "_run_cli_quick", fake_run_cli_quick)

    client = TestClient(create_app())
    response = client.get("/api/debug/lark-cli/account")

    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["authenticated"] is True
    assert data["account_label"] == "me@example.com"


def test_lark_cli_account_does_not_treat_bot_only_status_as_user_auth(monkeypatch, tmp_path) -> None:
    cli_bin = tmp_path / "lark-cli"
    cli_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    cli_bin.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    def fake_resolve_lark_cli_path(_: str) -> Path:
        return cli_bin

    def fake_run_cli_quick(command: list[str], cwd: str | None = None) -> dict[str, object]:
        if command[1:3] == ["config", "show"]:
            return {"returncode": 0, "stdout": '{"users":"(no logged-in users)"}', "stderr": ""}
        if command[1:3] == ["auth", "status"]:
            return {
                "returncode": 0,
                "stdout": '{"identity":"bot","note":"No user logged in. Only bot (tenant) identity is available."}',
                "stderr": "",
            }
        if command[1:3] == ["auth", "list"]:
            return {"returncode": 0, "stdout": "", "stderr": "No logged-in users. Run `lark-cli auth login` to log in."}
        return {"returncode": 1, "stdout": "", "stderr": "no user logged in"}

    from app.api.routes import debug

    monkeypatch.setattr(debug, "_resolve_lark_cli_path", fake_resolve_lark_cli_path)
    monkeypatch.setattr(debug, "_run_cli_quick", fake_run_cli_quick)

    client = TestClient(create_app())
    response = client.get("/api/debug/lark-cli/account")

    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["authenticated"] is False
    assert data["account_label"] == ""


def test_lark_cli_setup_job_parses_verification_url(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    checks = [
        {"configured": False, "authenticated": False, "account_label": ""},
        {"configured": True, "authenticated": False, "account_label": ""},
        {"configured": True, "authenticated": True, "account_label": "me@example.com"},
    ]

    def fake_check(include_doctor: bool = True) -> dict[str, object]:
        if len(checks) > 1:
            return checks.pop(0)
        return checks[0]

    def fake_step(job_id: str, step: str, message: str, args: list[str]) -> bool:
        from app.api.routes import debug

        debug._update_setup_job(job_id, step=step, message=message)
        debug._append_setup_output(
            job_id,
            f"打开以下链接配置应用: https://open.feishu.cn/page/cli?user_code=ABCD-EFGH&step={step}\n",
        )
        return True

    from app.api.routes import debug

    monkeypatch.setattr(debug, "_build_lark_cli_account_check", fake_check)
    monkeypatch.setattr(debug, "_run_interactive_cli_step", fake_step)
    debug.LARK_CLI_SETUP_JOBS.clear()

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/lark-cli/account/setup",
        json={"auth_domain": "im", "use_recommend": False, "force_new_app": False},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(20):
        status_response = client.get(f"/api/debug/lark-cli/account/setup/{job_id}")
        data = status_response.json()
        if data["status"] == "completed":
            break
    assert data["status"] == "completed"
    assert data["verification_url"].startswith("https://open.feishu.cn/page/cli")
    assert data["user_code"] == "ABCD-EFGH"
    assert data["account_label"] == "me@example.com"


def test_lark_cli_setup_reuses_running_job(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    from app.api.routes import debug

    job = debug.LarkCliSetupJob(job_id="existing", status="running")
    debug.LARK_CLI_SETUP_JOBS.clear()
    debug.LARK_CLI_SETUP_JOBS[job.job_id] = job

    client = TestClient(create_app())
    response = client.post(
        "/api/debug/lark-cli/account/setup",
        json={"auth_domain": "im", "use_recommend": False, "force_new_app": False},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "existing"
