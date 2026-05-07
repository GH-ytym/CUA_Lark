# CUA-Lark

CUA-Lark 是一个面向飞书桌面端的智能执行体原型。系统优先把自然语言任务解析为可确定执行的 `lark-cli` 操作；当任务依赖当前界面上下文、CLI 能力不足、权限异常或需要桌面接管时，再切换到 CUA（Computer Use Agent）通过视觉模型和鼠标键盘动作完成兜底。

当前项目由三部分组成：

- `backend/`：FastAPI 后端，负责任务受理、意图解析、CLI 执行、CUA 兜底、状态流和运行时配置。
- `frontend/`：Vite + React 前端，提供飞书侧边栏式聊天界面、消息记录树、状态流、轨迹面板和配置面板。
- `cua/`：桌面接管模块，包含截图、元素感知、动作执行、循环控制、记忆和验证逻辑。

## 功能概览

- 自然语言任务入口：`POST /api/agent/execute`
- 长连接状态流：`GET /api/executions/{task_id}/stream`
- 任务详情查询与取消：`GET /api/executions/{task_id}`、`POST /api/executions/{task_id}/cancel`
- 运行时检测和本地配置：`/api/debug/runtime-check`、`/api/debug/runtime-config`
- Qwen / DashScope 模型检测：`/api/debug/qwen/models`
- lark-cli 安装、启用、账号授权辅助：`/api/debug/lark-cli/*`
- CLI 优先执行，失败后由诊断策略决定是否触发 CUA
- 解析失败或未知意图可直接移交 CUA
- 前端展示聊天气泡、消息记录、横向状态流、轨迹面板和更多执行信息

## 项目结构

```text
.
├── backend/
│   ├── app/
│   │   ├── api/routes/          # FastAPI 路由
│   │   ├── core/                # 配置与日志
│   │   ├── domain/              # 能力、状态、统一模型
│   │   ├── integrations/        # lark-cli、Redis、视觉模型适配
│   │   ├── schemas/             # API 请求/响应模型
│   │   └── services/            # 编排、解析、CLI、CUA、状态流服务
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── features/execution/  # SSE 状态流 Hook
│   │   ├── pages/SidebarPage.tsx
│   │   ├── state/
│   │   └── types/
│   └── package.json
├── cua/
│   ├── agent/                   # CUA 循环控制
│   ├── operators/               # 鼠标键盘动作执行
│   ├── perception/              # 截图和元素感知
│   ├── memory/                  # 本地执行记忆
│   └── prompts/
├── shared/                      # 共享错误码等通用定义
├── data/                        # 本地检索数据，如收件人 SQLite
└── .env.example
```

## 环境要求

- Python 3.12+
- Node.js 与 npm
- 可用的飞书桌面端
- 可用的 `lark-cli`，并完成飞书账号授权
- DashScope / Qwen OpenAI-compatible API Key
- 可选：CUA 视觉模型的 OpenAI-compatible `base_url`、模型名和 API Key

## 配置

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

最少需要关注这些字段：

```env
DASHSCOPE_API_KEY=
QWEN_CHAT_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL=qwen3.6-max-preview

LARK_CLI_PATH=
LARK_CLI_WORKDIR=./runtime/lark-cli

CUA_MODEL_API_KEY=
CUA_MODEL_API_BASE=
CUA_MODEL_NAME=

VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_APP_NAME=CUA-Lark
```

说明：

- `DASHSCOPE_API_KEY` 用于自然语言解析和 CLI 失败诊断。
- `LARK_CLI_PATH` 为空时默认从 `PATH` 查找 `lark-cli`。
- `CUA_MODEL_*` 仅在需要桌面视觉兜底时使用。
- `EVENT_BACKEND` 默认使用内存状态流；如需 Redis，可配置 `EVENT_BACKEND=redis` 和 `REDIS_URL`。
- 根目录 `cua_memory.json` 已加入 `.gitignore`，作为本地运行记忆文件，不应提交。

## 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm install --prefix .\frontend
```

## 启动开发环境

启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir .\backend --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
npm run dev --prefix .\frontend -- --host 127.0.0.1 --port 5173
```

打开：

```text
http://127.0.0.1:5173
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health
```

## 运行时配置面板

前端右侧配置面板可以完成以下本地检查和配置：

- 检测 `.env`
- 保存 Qwen / DashScope 配置
- 检测可用模型
- 安装或启用 `lark-cli`
- 检测 lark-cli 应用配置与账号授权
- 配置 CUA 视觉模型

这些接口只面向本地开发使用，不应直接暴露到公网。

## 常用 API

提交自然语言任务：

```http
POST /api/agent/execute
Content-Type: application/json

{
  "message": "给梅家济发消息：“hello”",
  "session_id": "demo-session",
  "user_id": "demo-user",
  "conversation_type": "chat",
  "context_hint": ""
}
```

查询任务详情：

```http
GET /api/executions/{task_id}
```

订阅任务状态流：

```http
GET /api/executions/{task_id}/stream
```

取消任务：

```http
POST /api/executions/{task_id}/cancel
```

## 执行链路

1. 前端提交自然语言命令。
2. 后端创建任务并立即返回 `task_id`。
3. 前端通过 SSE 长连接订阅状态更新。
4. `IntentService` 解析任务并生成标准动作。
5. `OrchestratorService` 优先选择 CLI 执行确定性能力。
6. CLI 失败时，`CliFailureDiagnosisService` 判断是否应切换到 CUA。
7. CUA 接管时，`CuaService` 调用 `cua/agent/loop_runner.py` 驱动桌面操作。
8. 前端持续展示状态流、轨迹和最终结果。

## 测试与检查

后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
```

前端类型检查：

```powershell
npm run typecheck --prefix .\frontend
```

前端构建：

```powershell
npm run build --prefix .\frontend
```

## 开发注意事项

- 不要提交 `.env`、运行截图、缓存目录、`runtime/` 和本地记忆文件。
- `cua_memory.json` 是本机执行记忆，已经通过 `.gitignore` 忽略。
- CUA 会操作真实桌面，执行前应确认飞书客户端处于可控状态。
- 调试失败链路时优先查看前端轨迹面板和 `/api/executions/{task_id}` 返回的 steps。
- 涉及飞书真实账号、群聊或文档写入时，建议先用明确的小任务验证 CLI 和账号授权。
