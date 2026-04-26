# Day1 MVP 冻结范围（A 线）

## 冻结能力（仅首批）
- `message_send`：发送提醒或通知消息。
- `calendar_reschedule`：改期一个明确会议。
- `doc_create`：创建文档并写入基础内容。
- `sheet_update`：更新单元格或单行数据。

## 状态机
- 初始状态：`queued`
- 中间状态：`parsing`、`cli_running`、`cli_failed`、`cua_running`
- 终止状态：`completed`、`failed`、`canceled`

## 当前实现位置
- 状态枚举与流转规则：`backend/app/domain/enums.py`
- 状态机序列化模型：`backend/app/domain/models.py`
- 查询接口：`GET /api/agent/state-machine`
- MVP 查询接口：`GET /api/agent/mvp-scope`
- CUA 边界接口：`GET /api/agent/cua-boundary`（触发码与放弃原因与 `cua/trigger_rules.py` 对齐）
