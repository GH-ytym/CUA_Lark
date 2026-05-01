# Message Domain Qwen Real Check

- Generated at (UTC): `2026-05-01T07:06:24.751428+00:00`
- Recipient DB: `D:\pyprojects\FSAgent\data\lark_recipients.db`
- Model: `qwen3.6-max-preview`

| Capability | Natural language | Parse source | Parsed capability | CLI dry-run | Notes |
| --- | --- | --- | --- | --- | --- |
| `im.message_send` | 给梅家济发送：今天18:00前提交周报。 | rules | `im.message_send` | yes | 单聊发送 |
| `im.message_send` | 请帮我在小组里发：CI 已恢复，大家可以继续合并。 | rules | `im.message_send` | yes | 群聊发送 |
| `im.messages_search` | 搜索小组里关于发布的消息 | rules | `im.messages_search` | yes | 消息搜索 |
| `im.messages_reply` | 回复上一条消息：收到 | rules | `im.messages_reply` | no | 消息回复，天然依赖 message_id 或 thread_id; invalid cli payload: missing message_id/thread_id for lark-im +messages-reply |
| `im.chat_messages_list` | 列出小组最近的聊天记录 | rules | `im.chat_messages_list` | no | 聊天记录列表; invalid cli payload: missing chat_id/user_id for lark-im +chat-messages-list |
| `im.chat_search` | 搜索群聊 小组 | rules | `im.chat_search` | yes | 群搜索 |
| `im.chat_create` | 创建群，名字叫发布小组，描述是发布同步群 | rules | `im.chat_create` | yes | 建群 |
