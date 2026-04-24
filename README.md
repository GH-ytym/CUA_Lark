# CUA-Lark

面向飞书 AI 挑战赛的桌面智能体工程骨架，采用“Lark-CLI 精确执行优先，CUA 视觉保底降级”的融合架构。

## 项目目标

- 在飞书聊天会话或群组标签页中接收自然语言指令
- 优先将指令映射为 Lark-CLI 命令执行高确定性任务
- 在 CLI 不支持或执行失败时切换到 CUA 视觉操作完成 GUI 任务
- 将执行过程与结果实时回推到侧边栏界面和飞书会话

## 工作区结构

- `backend`：FastAPI 后端、编排服务、执行器、外部集成、测试占位
- `frontend`：React + Vite 侧边栏前端骨架
- `docs`：技术开发文档与方案说明
- `scripts`：Windows 本地开发环境初始化脚本

## 快速开始

1. 运行 `scripts/setup.ps1`
2. 根据 `.env.example` 生成并完善 `.env`
3. 启动后端：`.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --app-dir .\\backend`
4. 启动前端：`npm run dev --prefix .\\frontend`

## 当前状态

- 目录结构与环境脚本已就绪
- 源码文件暂时保留为单行注释占位，便于三人并行分工开发
- 详细设计见 `docs/technical-development.md`
