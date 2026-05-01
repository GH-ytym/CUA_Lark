# Day4 Message Smoke

- Generated at (UTC): `2026-05-01T07:06:24.808858+00:00`
- Recipient DB: `D:\pyprojects\FSAgent\data\lark_recipients.db`
- Rounds: `1` (total runs `4`)
- Execution path: `IntentService.parse -> LarkCliService.execute_action(dry_run=True)`

| Round | Case | Natural language | Expected CLI dry-run command | Parsed structured payload | Parsed CLI dry-run command | Compare | Execution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 给梅家济发送：今天18:00前提交周报。 | lark-cli im +messages-send --as bot --text 今天18:00前提交周报。 --user-id ou_2c273d74c8c50975348694bc69f34678 --dry-run | {"parse_source": "rules", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "ou_2c273d74c8c50975348694bc69f34678", "text": "今天18:00前提交周报", "identity": "bot"}, "note": "单聊，明确姓名"} | lark-cli im +messages-send --as bot --text 今天18:00前提交周报 --user-id ou_2c273d74c8c50975348694bc69f34678 --dry-run | mismatch | success=True, exit=0, cost=427.68ms |
| 1 | 2 | 跟刘海俊说："请确认明天评审材料" | lark-cli im +messages-send --as bot --text 请确认明天评审材料 --user-id ou_64c6927d31d3c695bd2369fb9136b691 --dry-run | {"parse_source": "rules", "capability_id": "im.message_send", "payload": {"chat_id": "", "user_id": "ou_64c6927d31d3c695bd2369fb9136b691", "text": "\"请确认明天评审材料\"", "identity": "bot"}, "note": "单聊，引号正文"} | lark-cli im +messages-send --as bot --text \"请确认明天评审材料\" --user-id ou_64c6927d31d3c695bd2369fb9136b691 --dry-run | mismatch | success=True, exit=0, cost=414.17ms |
| 1 | 3 | 请帮我在小组里发：CI 已恢复，大家可以继续合并。 | lark-cli im +messages-send --as bot --text "CI 已恢复，大家可以继续合并。" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | {"parse_source": "rules", "capability_id": "im.message_send", "payload": {"chat_id": "oc_7876d7cdaf5e6a888e44522b83c0470a", "user_id": "", "text": "CI 已恢复，大家可以继续合并", "identity": "bot"}, "note": "群聊，口语句式"} | lark-cli im +messages-send --as bot --text "CI 已恢复，大家可以继续合并" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | mismatch | success=True, exit=0, cost=378.54ms |
| 1 | 4 | 发送消息给小组：今晚 9 点发布，注意回归验证。 | lark-cli im +messages-send --as bot --text "今晚 9 点发布，注意回归验证。" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | {"parse_source": "rules", "capability_id": "im.message_send", "payload": {"chat_id": "oc_7876d7cdaf5e6a888e44522b83c0470a", "user_id": "", "text": "今晚 9 点发布，注意回归验证", "identity": "bot"}, "note": "群聊，命令句式"} | lark-cli im +messages-send --as bot --text "今晚 9 点发布，注意回归验证" --chat-id oc_7876d7cdaf5e6a888e44522b83c0470a --dry-run | mismatch | success=True, exit=0, cost=355.72ms |

## Summary

- Command match: `0/4`
- Execution success: `4/4`
