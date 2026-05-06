"""Debug routes for traceability during sprint integration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import threading
from urllib.parse import urlsplit, urlunsplit
import uuid

from fastapi import APIRouter, HTTPException, Request
import httpx
from pydantic import BaseModel, Field
from dotenv import dotenv_values, set_key

from app.core.config import get_settings

router = APIRouter(prefix="/debug", tags=["debug"])
LARK_CLI_PACKAGE_PATTERN = re.compile(
    r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*(?:@[A-Za-z0-9][A-Za-z0-9._~+-]*)?$"
)
DEFAULT_LARK_CLI_PACKAGE = "@larksuite/cli"
DEFAULT_LARK_CLI_INSTALL_DIR = Path("runtime/lark-cli")
LARK_CLI_URL_PATTERN = re.compile(r"https://(?:open|accounts)\.feishu\.cn/[^\s]+")
LARK_CLI_USER_CODE_PATTERN = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b")
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LARK_CLI_SETUP_JOBS: dict[str, "LarkCliSetupJob"] = {}
LARK_CLI_SETUP_LOCK = threading.RLock()


@dataclass
class LarkCliSetupJob:
    """In-memory state for one local lark-cli config/auth flow."""

    job_id: str
    status: str = "running"
    step: str = "check"
    message: str = "准备检查 lark-cli 配置"
    verification_url: str = ""
    user_code: str = ""
    output: str = ""
    error: str = ""
    account_label: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    account_check: dict[str, object] | None = field(default=None, repr=False)


class RuntimeConfigUpdate(BaseModel):
    """Editable runtime configuration fields from the local frontend."""

    dashscope_api_key: str = Field(default="", max_length=4096)
    qwen_chat_url: str = Field(default="", max_length=1000)
    qwen_model: str = Field(default="", max_length=128)
    lark_cli_path: str = Field(default="", max_length=1000)
    lark_cli_workdir: str = Field(default="", max_length=1000)
    cua_model_api_key: str = Field(default="", max_length=4096)
    cua_model_api_base: str = Field(default="", max_length=1000)
    cua_model_name: str = Field(default="", max_length=256)


class QwenModelProbeRequest(BaseModel):
    """Probe OpenAI-compatible Qwen model availability from frontend drafts or saved env."""

    dashscope_api_key: str = Field(default="", max_length=4096)
    qwen_chat_url: str = Field(default="", max_length=1000)
    qwen_model: str = Field(default="", max_length=256)


class LarkCliInstallRequest(BaseModel):
    """Install lark-cli into a local project runtime folder."""

    package_name: str = Field(default=DEFAULT_LARK_CLI_PACKAGE, min_length=1, max_length=256)
    registry_url: str = Field(default="", max_length=1000)


class LarkCliEnableRequest(BaseModel):
    """Enable an already installed lark-cli binary."""

    path: str = Field(min_length=1, max_length=1000)
    workdir: str = Field(default="", max_length=1000)


class LarkCliAccountSetupRequest(BaseModel):
    """Start a guided local account setup flow."""

    auth_domain: str = Field(default="im", max_length=200)
    use_recommend: bool = False
    force_new_app: bool = False


@router.get("/echo")
async def debug_echo(request: Request) -> dict[str, str]:
    """Return request metadata to validate middleware wiring."""
    request_id = getattr(request.state, "request_id", "missing")
    principal = getattr(request.state, "principal", "anonymous")
    return {"request_id": request_id, "principal": principal}


@router.get("/runtime-check")
async def runtime_check() -> dict[str, object]:
    """Return non-secret runtime readiness checks for the frontend setup panel."""
    settings = get_settings()
    env_path = Path(".env")
    node_path = shutil.which("node")
    npm_path = shutil.which("npm")
    lark_cli_resolved = shutil.which(settings.lark_cli_path)
    explicit_lark_path_exists = Path(settings.lark_cli_path).exists() if settings.lark_cli_path else False
    lark_cli_available = bool(lark_cli_resolved or explicit_lark_path_exists)
    lark_cli_workdir = _resolve_optional_path(settings.lark_cli_workdir)
    lark_account = _build_lark_cli_account_check(include_doctor=False) if lark_cli_available else {
        "configured": False,
        "authenticated": False,
        "account_label": "",
    }

    checks = [
        {
            "id": "env_file",
            "label": ".env 文件",
            "status": "ok" if env_path.exists() else "missing",
            "value": str(env_path.resolve()) if env_path.exists() else str(env_path.resolve()),
            "required": True,
            "hint": "在项目根目录创建 .env，参考 .env.example 或下方字段模板。",
        },
        {
            "id": "dashscope_api_key",
            "label": "DASHSCOPE_API_KEY",
            "status": "ok" if bool(settings.dashscope_api_key) else "missing",
            "value": "已配置" if settings.dashscope_api_key else "未配置",
            "required": True,
            "hint": "填写阿里云百炼 API Key；接口不会回显密钥内容。",
        },
        {
            "id": "qwen_chat_url",
            "label": "QWEN_CHAT_URL",
            "status": "ok" if bool(settings.qwen_chat_url) else "missing",
            "value": settings.qwen_chat_url or "",
            "required": True,
            "hint": "默认使用 DashScope OpenAI-compatible chat completions 地址。",
        },
        {
            "id": "qwen_model",
            "label": "QWEN_MODEL",
            "status": "ok" if bool(settings.qwen_model) else "missing",
            "value": settings.qwen_model or "",
            "required": True,
            "hint": "建议先用 qwen3.6-max；需要更快可换团队确认过的模型。",
        },
        {
            "id": "lark_cli",
            "label": "Lark CLI",
            "status": "ok" if lark_cli_available else "missing",
            "value": lark_cli_resolved or settings.lark_cli_path,
            "required": True,
            "hint": "安装并登录 lark-cli；若不在 PATH，设置 LARK_CLI_PATH 为绝对路径。",
        },
        {
            "id": "lark_cli_auth",
            "label": "飞书帐号授权",
            "status": "ok" if lark_account.get("authenticated") else "missing",
            "value": str(lark_account.get("account_label") or "未登录"),
            "required": True,
            "hint": "需要完成 lark-cli 应用配置和你的飞书帐号 OAuth 授权，才能用你的帐号发送消息。",
        },
        {
            "id": "lark_cli_workdir",
            "label": "LARK_CLI_WORKDIR",
            "status": "ok" if not settings.lark_cli_workdir or lark_cli_workdir.exists() else "warning",
            "value": str(lark_cli_workdir) if settings.lark_cli_workdir else "",
            "required": False,
            "hint": "lark-cli 执行工作目录；本地下载默认使用 ./runtime/lark-cli。",
        },
        {
            "id": "node_npm",
            "label": "Node.js / npm",
            "status": "ok" if node_path and npm_path else "missing",
            "value": f"node={node_path or '-'}; npm={npm_path or '-'}",
            "required": False,
            "hint": "一键下载 lark-cli 需要 Node.js 16+ 和 npm。",
        },
        {
            "id": "cua_model_api_key",
            "label": "CUA_MODEL_API_KEY",
            "status": "ok" if bool(os.getenv("CUA_MODEL_API_KEY", "")) else "missing",
            "value": "已配置" if os.getenv("CUA_MODEL_API_KEY", "") else "未配置",
            "required": False,
            "hint": "只在启用视觉兜底时必需；接口不会回显密钥内容。",
        },
        {
            "id": "cua_model_api_base",
            "label": "CUA_MODEL_API_BASE",
            "status": "ok" if bool(os.getenv("CUA_MODEL_API_BASE", "")) else "missing",
            "value": os.getenv("CUA_MODEL_API_BASE", ""),
            "required": False,
            "hint": "视觉模型 OpenAI-compatible base URL。",
        },
        {
            "id": "cua_model_name",
            "label": "CUA_MODEL_NAME",
            "status": "ok" if bool(os.getenv("CUA_MODEL_NAME", "")) else "missing",
            "value": os.getenv("CUA_MODEL_NAME", ""),
            "required": False,
            "hint": "视觉模型名称，例如团队提供的 endpoint/model id。",
        },
    ]

    return {
        "ready": all(item["status"] == "ok" for item in checks if item["required"]),
        "checks": checks,
        "env_template": {
            "DASHSCOPE_API_KEY": "填你的阿里云百炼 API Key",
            "QWEN_CHAT_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "QWEN_MODEL": settings.qwen_model or "qwen3.6-max",
            "LARK_CLI_PATH": settings.lark_cli_path or "lark-cli",
            "LARK_CLI_WORKDIR": settings.lark_cli_workdir or "./runtime/lark-cli",
            "CUA_MODEL_API_KEY": "启用视觉兜底时填写",
            "CUA_MODEL_API_BASE": "启用视觉兜底时填写",
            "CUA_MODEL_NAME": "启用视觉兜底时填写",
        },
        "install": {
            "backend": ".venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend",
            "frontend": "npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173",
            "dependencies": ".venv/bin/python -m pip install -r backend/requirements.txt && npm install --prefix frontend",
            "lark_cli_check": "lark-cli --version",
            "lark_cli_download": "npm install @larksuite/cli --prefix ./runtime/lark-cli",
            "lark_cli_enable": "把 LARK_CLI_PATH 设置为 ./runtime/lark-cli/node_modules/.bin/lark-cli",
            "lark_cli_account": "在前端点击“自动配置并登录”，按浏览器中的飞书页面确认授权。",
            "lark_cli_path_hint": "如果命令不存在，把 LARK_CLI_PATH 设置为 lark-cli 可执行文件绝对路径。",
        },
        "lark_account": lark_account,
    }


@router.post("/runtime-config")
async def update_runtime_config(payload: RuntimeConfigUpdate) -> dict[str, object]:
    """Update project .env from the local setup panel without echoing secrets."""
    env_path = Path(".env")
    env_path.touch(exist_ok=True)
    existing_values = dotenv_values(env_path)

    field_map = {
        "DASHSCOPE_API_KEY": payload.dashscope_api_key,
        "QWEN_CHAT_URL": payload.qwen_chat_url,
        "QWEN_MODEL": payload.qwen_model,
        "LARK_CLI_PATH": payload.lark_cli_path,
        "LARK_CLI_WORKDIR": payload.lark_cli_workdir,
        "CUA_MODEL_API_KEY": payload.cua_model_api_key,
        "CUA_MODEL_API_BASE": payload.cua_model_api_base,
        "CUA_MODEL_NAME": payload.cua_model_name,
    }

    updated_keys = _update_env_values(env_path=env_path, existing_values=existing_values, field_map=field_map)
    get_settings.cache_clear()
    check = await runtime_check()
    return {
        "updated_keys": updated_keys,
        "detail": check,
    }


@router.post("/qwen/models")
async def probe_qwen_models(payload: QwenModelProbeRequest) -> dict[str, object]:
    """Validate Qwen URL/API key and return available OpenAI-compatible models."""
    settings = get_settings()
    api_key = payload.dashscope_api_key.strip() or settings.dashscope_api_key
    chat_url = payload.qwen_chat_url.strip() or settings.qwen_chat_url
    requested_model = payload.qwen_model.strip() or settings.qwen_model

    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 DASHSCOPE_API_KEY。")
    if not chat_url:
        raise HTTPException(status_code=400, detail="请先填写 QWEN_CHAT_URL。")
    if not chat_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="QWEN_CHAT_URL 必须以 http:// 或 https:// 开头。")

    models_url = _models_url_from_chat_url(chat_url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(models_url, headers=headers)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="模型列表接口请求超时，请检查 URL 或网络。") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"模型列表接口请求失败：{exc}") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=400, detail="API Key 校验失败，请确认 DASHSCOPE_API_KEY 是否正确或是否有模型访问权限。")
    if response.status_code == 404:
        raise HTTPException(status_code=400, detail=f"模型列表地址不可用：{models_url}")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=400,
            detail=f"模型列表接口返回 HTTP {response.status_code}：{_truncate_output(response.text, limit=600)}",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="模型列表接口返回的不是 JSON，请检查 URL 是否为 OpenAI-compatible 服务。") from exc

    models = _extract_model_ids(data)
    selected_model = _select_model(requested_model=requested_model, models=models)
    selected_available = bool(selected_model and selected_model in models)
    return {
        "ok": True,
        "chat_url": chat_url,
        "models_url": models_url,
        "models": models,
        "selected_model": selected_model,
        "selected_available": selected_available,
        "message": "已获取可用模型列表。" if models else "接口可访问，但没有返回模型列表；可手动填写模型名。",
    }


@router.post("/lark-cli/install")
async def install_lark_cli(payload: LarkCliInstallRequest) -> dict[str, object]:
    """Download lark-cli with npm into project runtime and enable it in .env."""
    package_name = payload.package_name.strip() or DEFAULT_LARK_CLI_PACKAGE
    if not LARK_CLI_PACKAGE_PATTERN.fullmatch(package_name):
        raise HTTPException(status_code=400, detail="npm 包名格式不合法，请填写类似 @larksuite/cli 的包名。")

    registry_url = payload.registry_url.strip()
    if registry_url and not registry_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="registry 地址必须以 http:// 或 https:// 开头。")

    npm_bin = shutil.which("npm")
    if not npm_bin:
        raise HTTPException(status_code=400, detail="未检测到 npm，请先安装 Node.js 16+ 和 npm。")

    install_dir = DEFAULT_LARK_CLI_INSTALL_DIR.resolve()
    install_dir.mkdir(parents=True, exist_ok=True)
    package_json = install_dir / "package.json"
    if not package_json.exists():
        package_json.write_text('{"private": true, "dependencies": {}}\n', encoding="utf-8")

    command = [npm_bin, "install", package_name, "--save-exact"]
    if registry_url:
        command.extend(["--registry", registry_url])

    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=install_dir,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"lark-cli 下载超时：{exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法启动 npm：{exc}") from exc

    stdout = _truncate_output(proc.stdout)
    stderr = _truncate_output(proc.stderr)
    if proc.returncode != 0:
        detail = stderr or stdout or f"npm exited with code {proc.returncode}"
        raise HTTPException(status_code=500, detail=f"lark-cli 下载失败：{detail}")

    cli_path = _find_local_lark_cli_bin(install_dir)
    if cli_path is None:
        raise HTTPException(status_code=500, detail="npm 已执行，但未找到 node_modules/.bin/lark-cli。")

    updated_keys = _enable_lark_cli_path(path=cli_path, workdir=install_dir)
    check = await runtime_check()
    return {
        "ok": True,
        "message": f"已下载并启用 {package_name}",
        "package_name": package_name,
        "install_dir": str(install_dir),
        "bin_path": str(cli_path),
        "command": _render_command(command),
        "stdout": stdout,
        "stderr": stderr,
        "updated_keys": updated_keys,
        "detail": check,
    }


@router.post("/lark-cli/enable")
async def enable_lark_cli(payload: LarkCliEnableRequest) -> dict[str, object]:
    """Enable an existing lark-cli command or executable path in .env."""
    cli_path = _resolve_lark_cli_path(payload.path)
    workdir_path = _resolve_workdir_for_enable(payload.workdir)
    updated_keys = _enable_lark_cli_path(path=cli_path, workdir=workdir_path)
    check = await runtime_check()
    return {
        "ok": True,
        "message": "已启用 lark-cli",
        "install_dir": str(workdir_path) if workdir_path else "",
        "bin_path": str(cli_path),
        "updated_keys": updated_keys,
        "detail": check,
    }


@router.get("/lark-cli/account")
async def lark_cli_account_check() -> dict[str, object]:
    """Inspect local lark-cli app config and authorized account state."""
    return _build_lark_cli_account_check()


@router.post("/lark-cli/account/setup")
async def start_lark_cli_account_setup(payload: LarkCliAccountSetupRequest) -> dict[str, object]:
    """Start a guided config/auth flow for the local lark-cli account."""
    auth_domain = payload.auth_domain.strip() or "im"
    if not re.fullmatch(r"[a-z,]+", auth_domain):
        raise HTTPException(status_code=400, detail="授权域格式不合法，例如 im 或 im,contact。")

    with LARK_CLI_SETUP_LOCK:
        for existing in LARK_CLI_SETUP_JOBS.values():
            if existing.status == "running":
                return _job_response(existing)

        job = LarkCliSetupJob(job_id=uuid.uuid4().hex)
        LARK_CLI_SETUP_JOBS[job.job_id] = job

    thread = threading.Thread(
        target=_run_lark_cli_setup_job,
        args=(job.job_id, auth_domain, payload.use_recommend, payload.force_new_app),
        daemon=True,
    )
    thread.start()
    return _job_response(job)


@router.get("/lark-cli/account/setup/{job_id}")
async def get_lark_cli_account_setup(job_id: str) -> dict[str, object]:
    """Return the latest state for a guided lark-cli setup job."""
    return _get_job_response_or_404(job_id)


@router.post("/lark-cli/account/setup/{job_id}/cancel")
async def cancel_lark_cli_account_setup(job_id: str) -> dict[str, object]:
    """Cancel a running guided lark-cli setup job."""
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到 lark-cli 配置任务。")
        if job.status != "running":
            return _job_response(job)
        job.status = "canceled"
        job.message = "已取消配置流程"
        job.updated_at = datetime.now(UTC).isoformat()
        job.completed_at = job.updated_at
        process = job.process

    if process is not None and process.poll() is None:
        process.terminate()
    return _get_job_response_or_404(job_id)


def _update_env_values(
    env_path: Path,
    existing_values: dict[str, str | None],
    field_map: dict[str, str],
) -> list[str]:
    updated_keys: list[str] = []
    for key, value in field_map.items():
        next_value = value.strip()
        if not next_value:
            continue
        if existing_values.get(key) == next_value:
            continue
        set_key(env_path, key, next_value, quote_mode="auto")
        os.environ[key] = next_value
        updated_keys.append(key)
    return updated_keys


def _enable_lark_cli_path(path: Path, workdir: Path | None) -> list[str]:
    env_path = Path(".env")
    env_path.touch(exist_ok=True)
    updates = {"LARK_CLI_PATH": str(path)}
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        updates["LARK_CLI_WORKDIR"] = str(workdir)
    updated_keys = _update_env_values(
        env_path=env_path,
        existing_values=dotenv_values(env_path),
        field_map=updates,
    )
    get_settings.cache_clear()
    return updated_keys


def _models_url_from_chat_url(chat_url: str) -> str:
    parsed = urlsplit(chat_url.strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    elif path.endswith("/completions"):
        path = path[: -len("/completions")]
    models_path = f"{path}/models" if path else "/models"
    return urlunsplit((parsed.scheme, parsed.netloc, models_path, "", ""))


def _extract_model_ids(payload: object) -> list[str]:
    data: object = payload
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("models", []))
    raw_ids: list[str] = []
    if isinstance(data, list):
        for item in data:
            model_id = ""
            if isinstance(item, str):
                model_id = item
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            if model_id:
                raw_ids.append(model_id)
    unique: list[str] = []
    seen: set[str] = set()
    for model_id in raw_ids:
        if model_id in seen:
            continue
        seen.add(model_id)
        unique.append(model_id)
    return unique


def _select_model(requested_model: str, models: list[str]) -> str:
    requested = requested_model.strip()
    if requested:
        if not models or requested in models:
            return requested
        requested_lower = requested.lower()
        for model in models:
            if model.lower() == requested_lower:
                return model
    for preferred in ("qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"):
        if preferred in models:
            return preferred
    return models[0] if models else requested


def _build_lark_cli_account_check(include_doctor: bool = True) -> dict[str, object]:
    cli_bin = _configured_lark_cli_bin()
    workdir = _configured_lark_cli_workdir()
    config_result = _run_cli_quick([cli_bin, "config", "show"], cwd=workdir)
    auth_result = _run_cli_quick([cli_bin, "auth", "status"], cwd=workdir)
    auth_list_result = _run_cli_quick([cli_bin, "auth", "list"], cwd=workdir)
    doctor_result = _run_cli_quick([cli_bin, "doctor"], cwd=workdir) if include_doctor else None
    account_label = _extract_account_label(auth_result["stdout"], auth_list_result["stdout"])
    configured = config_result["returncode"] == 0
    authenticated = bool(account_label) and not _is_no_logged_in_user(auth_result["stdout"], auth_list_result["stderr"])
    return {
        "configured": configured,
        "authenticated": authenticated,
        "account_label": account_label if authenticated else "",
        "cli_path": cli_bin,
        "workdir": workdir or "",
        "config": config_result,
        "auth_status": auth_result,
        "auth_list": auth_list_result,
        "doctor": doctor_result,
    }


def _run_lark_cli_setup_job(
    job_id: str,
    auth_domain: str,
    use_recommend: bool,
    force_new_app: bool,
) -> None:
    try:
        account_check = _build_lark_cli_account_check(include_doctor=False)
        _update_setup_job(
            job_id,
            step="check",
            message="已完成本机 lark-cli 状态检查",
            account_check=account_check,
        )
        if not account_check.get("configured") or force_new_app:
            config_args = ["config", "init", "--new", "--lang", "zh"]
            if not _run_interactive_cli_step(
                job_id=job_id,
                step="config",
                message="等待在浏览器完成飞书应用配置",
                args=config_args,
            ):
                return
        else:
            _update_setup_job(job_id, step="config", message="已检测到 lark-cli 应用配置，跳过应用配置")

        account_check = _build_lark_cli_account_check(include_doctor=False)
        if not account_check.get("authenticated"):
            auth_args = ["auth", "login"]
            if use_recommend:
                auth_args.append("--recommend")
            else:
                auth_args.extend(["--domain", auth_domain])
            if not _run_interactive_cli_step(
                job_id=job_id,
                step="auth",
                message="等待在浏览器完成你的飞书帐号授权",
                args=auth_args,
            ):
                return
        else:
            _update_setup_job(job_id, step="auth", message="已检测到飞书帐号授权，跳过登录授权")

        final_check = _build_lark_cli_account_check(include_doctor=True)
        if final_check.get("configured") and final_check.get("authenticated"):
            _finish_setup_job(
                job_id,
                status="completed",
                step="done",
                message="飞书帐号已配置并授权，可以用你的帐号发送消息",
                account_check=final_check,
            )
        else:
            _finish_setup_job(
                job_id,
                status="failed",
                step="verify",
                message="配置流程结束，但未检测到完整授权",
                error=_compact_cli_error(final_check),
                account_check=final_check,
            )
    except Exception as exc:  # noqa: BLE001
        _finish_setup_job(
            job_id,
            status="failed",
            step="error",
            message="自动配置流程异常退出",
            error=str(exc),
        )


def _run_interactive_cli_step(job_id: str, step: str, message: str, args: list[str]) -> bool:
    cli_bin = _configured_lark_cli_bin()
    workdir = _configured_lark_cli_workdir()
    command = [cli_bin, *args]
    _update_setup_job(job_id, step=step, message=message, output=f"$ {_render_command(command)}\n")
    try:
        process = subprocess.Popen(
            command,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        _finish_setup_job(job_id, status="failed", step=step, message="无法启动 lark-cli", error=str(exc))
        return False

    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            return False
        job.process = process

    assert process.stdout is not None
    for line in process.stdout:
        with LARK_CLI_SETUP_LOCK:
            job = LARK_CLI_SETUP_JOBS.get(job_id)
            if job is None or job.status == "canceled":
                if process.poll() is None:
                    process.terminate()
                return False
        _append_setup_output(job_id, line)

    returncode = process.wait()
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is not None:
            job.process = None
        if job is None or job.status == "canceled":
            return False

    if returncode != 0:
        _finish_setup_job(
            job_id,
            status="failed",
            step=step,
            message=f"lark-cli {step} 步骤失败",
            error=f"exit_code={returncode}",
        )
        return False
    _update_setup_job(job_id, step=step, message=f"{step} 步骤已完成")
    return True


def _append_setup_output(job_id: str, chunk: str) -> None:
    clean_chunk = _clean_cli_output(chunk)
    url_match = LARK_CLI_URL_PATTERN.search(clean_chunk)
    code_match = LARK_CLI_USER_CODE_PATTERN.search(clean_chunk)
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            return
        job.output = _truncate_output(job.output + clean_chunk, limit=12000)
        if url_match:
            job.verification_url = url_match.group(0)
        if code_match:
            job.user_code = code_match.group(0)
        if job.verification_url:
            job.message = "请打开飞书授权链接，并使用当前电脑已登录的飞书帐号确认"
        job.updated_at = datetime.now(UTC).isoformat()


def _update_setup_job(
    job_id: str,
    *,
    step: str | None = None,
    message: str | None = None,
    output: str | None = None,
    account_check: dict[str, object] | None = None,
) -> None:
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            return
        if step is not None:
            job.step = step
        if message is not None:
            job.message = message
        if output is not None:
            job.output = _truncate_output(output, limit=12000)
        if account_check is not None:
            job.account_check = account_check
            job.account_label = str(account_check.get("account_label") or "")
        job.updated_at = datetime.now(UTC).isoformat()


def _finish_setup_job(
    job_id: str,
    *,
    status: str,
    step: str,
    message: str,
    error: str = "",
    account_check: dict[str, object] | None = None,
) -> None:
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            return
        job.status = status
        job.step = step
        job.message = message
        job.error = error
        job.updated_at = datetime.now(UTC).isoformat()
        job.completed_at = job.updated_at
        if account_check is not None:
            job.account_check = account_check
            job.account_label = str(account_check.get("account_label") or "")


def _get_job_response_or_404(job_id: str) -> dict[str, object]:
    with LARK_CLI_SETUP_LOCK:
        job = LARK_CLI_SETUP_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到 lark-cli 配置任务。")
        return _job_response(job)


def _job_response(job: LarkCliSetupJob) -> dict[str, object]:
    detail = job.account_check
    if job.status in {"completed", "failed", "canceled"}:
        detail = _build_lark_cli_account_check(include_doctor=False)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "step": job.step,
        "message": job.message,
        "verification_url": job.verification_url,
        "user_code": job.user_code,
        "output": _truncate_output(job.output, limit=12000),
        "error": job.error,
        "account_label": job.account_label,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "account": detail,
    }


def _configured_lark_cli_bin() -> str:
    settings = get_settings()
    return str(_resolve_lark_cli_path(settings.lark_cli_path or "lark-cli"))


def _configured_lark_cli_workdir() -> str | None:
    settings = get_settings()
    workdir = _resolve_optional_path(settings.lark_cli_workdir) if settings.lark_cli_workdir else None
    return str(workdir) if workdir and workdir.exists() else None


def _run_cli_quick(command: list[str], cwd: str | None = None) -> dict[str, object]:
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            cwd=cwd,
        )
    except Exception as exc:  # noqa: BLE001
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": proc.returncode,
        "stdout": _truncate_output(_clean_cli_output(proc.stdout), limit=6000),
        "stderr": _truncate_output(_clean_cli_output(proc.stderr), limit=6000),
    }


def _extract_account_label(auth_stdout: object, list_stdout: object) -> str:
    for raw in (auth_stdout, list_stdout):
        text = str(raw or "").strip()
        if not text:
            continue
        if _is_no_logged_in_user(text):
            continue
        parsed = _parse_first_json(text)
        if parsed is not None:
            label = _find_account_label(parsed)
            if label:
                return label
        for line in text.splitlines():
            lower = line.lower()
            if "no user logged in" in lower or "no logged-in users" in lower:
                continue
            if any(key in lower for key in ("email", "username", "useropenid", "name", "open_id", "union_id")):
                return line.strip()
    return ""


def _find_account_label(value: object) -> str:
    if isinstance(value, dict):
        for key in (
            "email",
            "name",
            "display_name",
            "en_name",
            "cn_name",
            "userName",
            "userOpenId",
            "open_id",
            "openId",
            "union_id",
            "unionId",
            "user_id",
            "userId",
        ):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for nested in value.values():
            label = _find_account_label(nested)
            if label:
                return label
    if isinstance(value, list):
        for item in value:
            label = _find_account_label(item)
            if label:
                return label
    return ""


def _parse_first_json(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _is_no_logged_in_user(*values: object) -> bool:
    text = "\n".join(str(value or "") for value in values).lower()
    return "no user logged in" in text or "no logged-in users" in text or "(no logged-in users)" in text


def _compact_cli_error(check: dict[str, object]) -> str:
    for key in ("config", "auth_status", "auth_list", "doctor"):
        value = check.get(key)
        if not isinstance(value, dict):
            continue
        if value.get("returncode") == 0:
            continue
        stderr = str(value.get("stderr") or "").strip()
        stdout = str(value.get("stdout") or "").strip()
        if stderr or stdout:
            return f"{key}: {stderr or stdout}"
    return "未检测到完整配置或授权。"


def _clean_cli_output(text: str | None) -> str:
    cleaned = ANSI_PATTERN.sub("", text or "")
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "████" in line or "▄▄" in line or "▀" in line:
            continue
        if any(marker in line for marker in ("使用飞书 / Lark", "打开以下链接", "正在获取", "等待配置", "等待授权")):
            lines.append(line)
            continue
        if LARK_CLI_URL_PATTERN.search(line) or LARK_CLI_USER_CODE_PATTERN.search(line):
            lines.append(line)
            continue
        if line.startswith("$ "):
            lines.append(line)
    return "\n".join(lines) if lines else cleaned


def _resolve_lark_cli_path(raw_path: str) -> Path:
    text = raw_path.strip()
    path = Path(text).expanduser()
    if path.is_file():
        return path.absolute()
    found = shutil.which(text)
    if found:
        return Path(found).absolute()
    cmd_found = shutil.which(f"{text}.cmd")
    if cmd_found:
        return Path(cmd_found).absolute()
    raise HTTPException(status_code=400, detail="未找到 lark-cli，可先点击下载，或填写可执行文件绝对路径。")


def _resolve_workdir_for_enable(raw_workdir: str) -> Path | None:
    text = raw_workdir.strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _resolve_optional_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _find_local_lark_cli_bin(install_dir: Path) -> Path | None:
    candidates = [
        install_dir / "node_modules" / ".bin" / "lark-cli",
        install_dir / "node_modules" / ".bin" / "lark-cli.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.absolute()
    return None


def _truncate_output(output: str | None, limit: int = 4000) -> str:
    text = (output or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...（已截断）"


def _render_command(command: list[str]) -> str:
    return " ".join(command)
