# Day4 消息域真实链路冒烟测试

- 生成时间（UTC）：`2026-05-01T05:36:08.194498+00:00`
- 收件人库：`D:\pyprojects\FSAgent\data\lark_recipients.db`
- 测试轮次：`1`（总用例执行 `4` 次）
- 说明：执行链路走 `LarkCliService.execute`，并统一使用 `--dry-run` 防止真实发消息。

| 轮次 | 编号 | 自然语言消息 | 理论 CLI 真实命令（dry-run） | Qwen/规则结构化命令 | 结构化命令生成 CLI | 对比结论 | 执行结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 给梅家济发送：今天18:00前提交周报。 | lark-cli im +messages-send --as bot --text 今天18:00前提交周报。 --user-id ou_2c273d74c8c50975348694bc69f34678 --dry-run | {"parse_source": "qwen", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "ou_2c273d74c8c50975348694bc69f34678", "text": "今天18:00前提交周报。", "identity": "bot"}, "note": "单聊明确姓名"} | lark-cli im +messages-send --as bot --text 今天18:00前提交周报。 --user-id ou_2c273d74c8c50975348694bc69f34678 --dry-run | 一致 | success=True, exit=0, cost=328.01ms |
| 1 | 2 | 给刘海俊说："请确认明天评审材料" | lark-cli im +messages-send --as bot --text 请确认明天评审材料 --user-id ou_64c6927d31d3c695bd2369fb9136b691 --dry-run | {"parse_source": "qwen", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "ou_64c6927d31d3c695bd2369fb9136b691", "text": "请确认明天评审材料", "identity": "bot"}, "note": "单聊引号正文"} | lark-cli im +messages-send --as bot --text 请确认明天评审材料 --user-id ou_64c6927d31d3c695bd2369fb9136b691 --dry-run | 一致 | success=True, exit=0, cost=317.62ms |
| 1 | 3 | 请帮我在CUA-Lark-4里发：CI 已恢复，大家可以继续合并。 | lark-cli im +messages-send --as bot --text "CI 已恢复，大家可以继续合并。" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | {"parse_source": "qwen", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "", "text": "CI 已恢复，大家可以继续合并。", "identity": "bot"}, "note": "群聊口语化"} | missing chat_id/user_id for lark-im +messages-send | 不一致（结构化命令缺参：missing chat_id/user_id for lark-im +messages-send） | success=False, code=result_invalid, reason=invalid cli payload: missing chat_id/user_id for lark-im +messages-send |
| 1 | 4 | 发送消息给CUA-Lark-4：今晚 9 点发布，注意回归验证。 | lark-cli im +messages-send --as bot --text "今晚 9 点发布，注意回归验证。" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | {"parse_source": "qwen", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "", "text": "今晚 9 点发布，注意回归验证。", "identity": "bot"}, "note": "群聊倒装句"} | missing chat_id/user_id for lark-im +messages-send | 不一致（结构化命令缺参：missing chat_id/user_id for lark-im +messages-send） | success=False, code=result_invalid, reason=invalid cli payload: missing chat_id/user_id for lark-im +messages-send |

## 汇总

- 命令构建一致率：`2/4`
- 执行成功率：`2/4`
