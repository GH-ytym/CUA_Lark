# Message Domain Capability Smoke

- Generated at (UTC): `2026-05-01T05:33:44.882732+00:00`
- Recipient DB: `D:\pyprojects\FSAgent\data\lark_recipients.db`

| Capability | Natural language | Parsed capability | Full NL chain | CLI dry-run | Notes |
| --- | --- | --- | --- | --- | --- |
| `im.message_send` | 请在CUA-Lark-4里发：今晚九点发布，注意回归验证。 | `im.message_send` | yes | yes | 群聊发送，需要 chat_hint -> chat_id 解析 |
| `im.messages_search` | 搜索CUA-Lark-4里关于发布的消息 | `im.messages_search` | yes | yes | 消息搜索，需要 chat_hint -> chat_id 解析 |
| `im.messages_reply` | 回复上一条消息：收到 | `im.messages_reply` | no | no | 缺少 message_id/thread_id，当前不能只靠自然语言直接执行 |
| `im.chat_messages_list` | 列出CUA-Lark-4最近的聊天记录 | `im.chat_messages_list` | no | yes | 规则链路可解析；Qwen 完整 smoke 还需单独验证 |
| `im.chat_search` | 搜索群聊 CUA-Lark-4 | `im.chat_search` | no | yes | 不依赖 ID，可执行，但当前不是 Day5 MVP 主链路 |
| `im.chat_create` | 创建群，名字叫发布小组，描述是发布同步群 | `im.chat_create` | no | yes | 可执行，但真实创建通常还要成员与权限确认 |
