# 将前端接入为飞书网页应用

## 当前结论

可以接。当前 React 页面已经适合作为飞书网页应用或侧边栏入口，开发环境入口为：

- 本地前端：`http://127.0.0.1:5173/`
- 本地后端：`http://127.0.0.1:8000`

飞书正式环境通常要求公网 HTTPS 地址，所以本地调试需要使用内网穿透或部署到服务器后再配置到飞书开放平台。

## 本地运行

```bash
cd /home/jmyj/下载/FeiShu_CUA_LARK/frontend
npm install
npm run dev -- --host 127.0.0.1
```

浏览器打开：`http://127.0.0.1:5173/`

## 飞书开放平台配置步骤

1. 打开飞书开放平台，进入目标应用。
2. 在“应用能力”中启用网页应用、侧边栏或 AppLink 入口（按比赛要求选择）。
3. 将前端入口 URL 配置为部署后的 HTTPS 地址，例如：`https://your-domain.example.com/`。
4. 如果需要后端接口，将后端 API 地址配置到前端环境变量 `VITE_API_BASE_URL`。
5. 在“安全设置 / 重定向 URL / 可信域名”中加入前端域名和后端域名。
6. 发布应用版本，并把应用安装到测试企业或测试群。

## 环境变量

前端需要：

```env
VITE_APP_NAME=CUA-Lark
VITE_API_BASE_URL=https://your-api-domain.example.com
VITE_FEISHU_APP_ENTRY_URL=https://your-frontend-domain.example.com
```

后端需要：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_APP_LINK_TOKEN=xxx
FEISHU_VERIFICATION_TOKEN=xxx
FEISHU_ENCRYPT_KEY=xxx
FRONTEND_ORIGIN=https://your-frontend-domain.example.com
```

## 开发期临时公网调试

如果暂时没有服务器，可以用内网穿透工具把 `5173` 端口映射为 HTTPS 地址，然后把该 HTTPS 地址填到飞书开放平台。

示例流程：

1. 本地启动前端：`npm run dev -- --host 0.0.0.0`
2. 使用内网穿透生成 HTTPS 地址。
3. 将 HTTPS 地址填入飞书网页应用入口。
4. 更新 `.env` 中的 `VITE_FEISHU_APP_ENTRY_URL`。

## 当前前端已做的适配

- 页面顶部展示当前运行容器：浏览器预览或飞书客户端。
- 页面展示前端入口与后端 API，便于飞书配置时核对。
- UI 使用单栏/双栏自适应布局，适合飞书侧边栏窄屏容器。

## 后续需要补齐

- 接入飞书 JS SDK 获取用户身份与会话上下文。
- 后端增加飞书事件回调校验与鉴权。
- 前端提交任务时附带 `open_id`、`tenant_key`、`chat_id` 等上下文。