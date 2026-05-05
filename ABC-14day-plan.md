# ABC 14天逐日排期（飞书 AI 挑战赛）

## A表（后端/编排负责人）

| Day | 主任务 | 当日验收标准 | 备任务（若提前完成） |
| --- | --- | --- | --- |
| 1 | 冻结 MVP 能力范围；设计 Agent 状态机 | 产出状态流转图（解析/确认/CLI/CUA/完成/失败/取消） | 起草统一错误码 |
| 2 | 搭 FastAPI 工程骨架、请求上下文、基础配置 | 本地可启动；健康检查、CORS、请求链路 ID 可验证 | 建立项目日志规范 |
| 3 | 意图解析与标准动作模型 v1 | 自然语言可解析为有序 `tasks[n].capability + payload + executor_hint`，支持 3-4 个跨域任务拆分 | 增加参数缺失提示 |
| 4 | CLI 通用执行器与结果归一化 | 任意 CLI 调用可返回统一 `ExecutorResult`，含 stdout/stderr/耗时/错误码 | 增加 dry-run 调试模式 |
| 5 | MVP 能力 1：`im.message_send` | 发消息链路可执行；支持联系人/群解析、幂等键、权限错误归一化 | 增加消息回复/搜索预研 |
| 6 | 任务编排器 v1 | API 接收任务后可创建 `task_id`，保存有序 `planned_actions`，并按顺序执行可落地任务 | 暴露任务详情查询接口 |
| 7 | CLI 失败到 CUA 的回退闭环 | CLI 失败后能按整数错误码组装 fallback request、触发 CUA 执行，并回写最终状态与失败归因 | 回退原因写入日志 |
| 8 | 超时、取消、重试机制 | CLI/CUA 执行超时可中断；重试次数、退避策略可配置；取消接口可用 | 失败补偿策略草案 |
| 9 | 执行进度流与前端联调接口 | `/executions/{task_id}/stream` 可输出 queued/running/fallback/completed/failed/canceled | 保留 Redis 队列接口设计 |
| 10 | 可观测性（链路 ID + 结构化日志） | 单次任务可按 chain_id 完整追踪，含 CLI/CUA 步骤、耗时、失败原因 | 暴露调试查询接口 |
| 11 | 扩展 MVP 能力 2：日程或文档二选一 | `calendar.create/reschedule` 或 `docs.create/update` 至少 1 条真实 CLI 链路跑通 | 记录未接能力的 CUA fallback 策略 |
| 12 | 后端单测与集成测试 | 编排器、CLI 执行、取消/超时、CLI->CUA 回退路径有测试覆盖 | 补充边界输入测试 |
| 13 | 演示脚本与稳定数据集 | 演示脚本一次通过率高；至少包含成功、权限失败、CUA 接管 3 类案例 | 准备答辩技术要点 |
| 14 | 封板与发布说明 | 冻结版本；发布文档可复现；环境、权限、演示步骤清晰 | 预留现场应急脚本 |

### A线 CLI Tool Capability Registry

将原来的“按业务做适配器”改为“Capability Registry”。

- 核心抽象：`capability_id + cli_command + required_payload + identity + scopes + fallback_policy`
- MVP 必做：`im.message_send`
- 优先候选：`im.messages_reply`、`im.messages_search`、`calendar.create`、`calendar.reschedule`、`docs.create`、`docs.update`、`sheets.update`
- 支撑能力：`contact.search` 用于人/群解析，`task.create` 用于执行后落待办，`mail.send` 用于通知补充链路
- 编排器不直接按 `lark-im/lark-doc` 分支判断，只调用 capability registry 生成 CLI invocation
- 未接入或执行失败的 capability 统一进入 CUA fallback 判断
- 本轮明确不做多任务规划：每次请求只生成一个 `StandardAction`，`action_plan` 仅用于说明，不参与执行拆分

### A/day7 补充说明

- 允许触发 CUA 的 CLI 整数错误码：`1` 限流、`2` 不支持、`3` 权限问题、`4` 输入或结果无效、`5` 执行错误、`6` 超时、`7` 必须切换执行器。
- fallback request 至少包含：`task_id`、`raw_message`、`standard_action`、`cli_error_code`、`cli_payload`、`cua_request`。
- 状态流转必须保留：`cli_finished -> cua_started -> cua_finished`；若 CUA 成功则写 `completed`，若 CUA 失败则写 `failed`，并记录最终 `cua_error_code`。
- 日志与回包都要保留调试字段：`error.code` 使用整数，`error.name` 保留字符串别名，`triggered_by.cli_error_code` 回写原始 CLI 触发码。
- 演示验收至少覆盖两类案例：`CLI 权限失败 -> CUA 接管成功`，以及 `CLI 失败 -> CUA 也失败并回写最终错误码`。

### A/day8 补充说明

- 重试策略落到 `RetryService`：默认最多 2 次尝试，仅对统一错误码 `1/5/6`（限流/执行错误/超时）重试；`3/4`（权限/输入或结果无效）不重试，继续按现有规则进入 CUA fallback 判断。
- CLI timeout 继续由现有 `lark_cli_timeout_seconds` 控制，超时会归一到错误码 `6`，并纳入同一重试策略。
- 新增 `POST /api/executions/{task_id}/cancel`：queued/parsing/running-like 的内存任务可标记为 `canceled`；已完成、失败、已取消的终态任务不被改写。
- 编排器在每个 planned action 执行前、以及 CUA fallback 前检查取消状态；本轮不引入后台队列，也不承诺中断已经运行中的 OS 子进程，Day9 再扩展为可中断长任务。
- 日程域本轮补齐 `calendar.create`、`calendar.agenda`、`calendar.freebusy` 的自然语言 -> `StandardAction` -> capability registry -> `lark-cli calendar +create/+agenda/+freebusy` 可执行链路。
- `calendar.reschedule` 先保证 `event_hint/source_time/target_time/target_start_time/target_end_time/calendar_id/event_id` 结构化输出；无 `event_id` 时保持 structured-only，避免误改真实日程。

### A/day3 与 day6 补充说明

- day3 多任务解析目标：一条自然语言可拆成 3-4 个子任务，保持用户原始顺序，不做并行重排。
- 结构化输出统一写入 `structured_command.tasks[]`，每项至少包含：`order`、`raw_message`、`capability_id`、`payload`、`missing_fields`。
- day6 编排目标：`planned_actions` 顺序保存在任务对象中；消息域走完整 CLI/CUA 执行链路，其他未打通域先保留 structured-only 结果，不阻塞后续顺序任务。
- 本轮仍不做真正的多任务并行执行、依赖图优化或父子任务重试树，只做顺序拆分与顺序安排。

## B表（CUA/视觉保底负责人）

| Day | 主任务                  | 当日验收标准           | 备任务（若提前完成） |
| --- | -------------------- | ---------------- | ---------- |
| 1   | 定义 CUA 触发边界与动作原语清单   | 明确“何时接管、何时放弃”规则  | 列风险场景清单    |
| 2   | CUA 执行器骨架（截图-识别-动作）  | 可完成最小动作链路        | 定义统一输入输出结构 |
| 3   | 元素识别接口与数据格式          | 能返回候选元素与置信度      | 增加元素类型标签   |
| 4   | 动作原语1：点击/输入/回车       | 基本交互可稳定执行        | 增加动作失败重试   |
| 5   | 截图采集与坐标校准            | 多分辨率下坐标误差可控      | 建立坐标换算工具   |
| 6   | 置信度阈值与二次确认逻辑         | 低置信度场景可安全降级      | 增加确认提示文案   |
| 7   | 接入后端回退闭环（被动触发）       | CLI失败后 CUA 可接管完成 | 记录接管原因     |
| 8   | 动作回滚与安全停止            | 可在异常时中止并留痕       | 增加“最后安全点”  |
| 9   | 动作后校验（多轮截图确认）        | 每步动作后有结果校验机制     | 降低误操作率     |
| 10  | CUA 轨迹日志（识别框+动作序列）   | 单任务轨迹可回放排障       | 导出轨迹摘要     |
| 11  | CUA 回归用例（核心页面）       | 关键页面用例可重复通过      | 增加失败样本集    |
| 12  | 联调修复高优问题             | P0/P1 CUA 问题清零   | 调参与阈值固化    |
| 13  | 准备“CLI失败->CUA接管”演示案例 | 2个保底案例稳定复现       | 准备风险说明话术   |
| 14  | 封板与现场预案              | 现场网络/分辨率变化有应对方案  | 备用演示路径准备   |

## C表（前端/集成负责人）

| Day | 主任务                 | 当日验收标准          | 备任务（若提前完成）   |
| --- | ------------------- | --------------- | ------------ |
| 1   | 侧边栏信息架构与交互线框        | 线框评审通过          | 定义组件拆分方案     |
| 2   | React 工程骨架与路由/状态管理  | 页面可运行；基础布局完成    | 接入 UI 主题变量   |
| 3   | 聊天输入与任务卡片 UI        | 可提交指令并展示任务卡     | 增加输入校验       |
| 4   | 实时状态展示（排队/执行/完成/失败） | 状态流可正确切换        | 加载/空态样式完善    |
| 5   | 结果详情页（步骤、耗时、原因）     | 可查看单任务完整详情      | 错误态可读性优化     |
| 6   | 流式更新与失败重试交互         | 执行中可持续刷新        | 增加手动刷新机制     |
| 7   | 首次全链路联调（前后端+CUA）    | 一条端到端链路跑通       | 记录联调问题单      |
| 8   | 异常态 UI（超时/中断/权限不足）  | 异常提示完整且可操作      | 统一错误展示组件     |
| 9   | 性能优化（首屏/重渲染）        | 首屏与交互明显更流畅      | 精简无效请求       |
| 10  | 调试视图（轨迹面板）          | 可查看链路ID与关键步骤    | 增加筛选与搜索      |
| 11  | 前端冒烟测试（核心流程）        | 提交-执行-结果链路可自动验证 | 补充跨浏览器检查     |
| 12  | 联调修复高优问题            | P0/P1 前端问题清零    | 文案与引导优化      |
| 13  | 演示模式页面（大字状态/高亮）     | 演示观感稳定清晰        | 准备讲解标注层      |
| 14  | 封板与讲稿联动彩排           | 演示脚本按时走完        | 准备 UI 应急降级开关 |
