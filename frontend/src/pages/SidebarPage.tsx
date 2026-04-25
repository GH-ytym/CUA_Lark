import { CommandComposer } from "../components/chat/CommandComposer";
import { ExecutionFeed } from "../components/chat/ExecutionFeed";
import { ResultDetail } from "../components/status/ResultDetail";
import { StatusTimeline } from "../components/status/StatusTimeline";
import { getFeishuRuntimeConfig } from "../lib/api";

export function SidebarPage() {
	const feishuConfig = getFeishuRuntimeConfig();

	return (
		<main className="sidebar-page">
			<section className="hero-card" aria-labelledby="hero-title">
				<div>
					<p className="eyebrow">信息架构线框</p>
					<h2 id="hero-title">从“输入指令”到“结果复盘”的单栏闭环</h2>
					<p>
						首日版本聚焦侧边栏核心路径：聊天输入、任务卡片、状态时间线、结果详情与后续调试入口，便于团队评审交互范围。
					</p>
				</div>
				<div className="hero-metrics" aria-label="首日验收项">
					<span>4 个核心区块</span>
					<span>CLI 优先</span>
					<span>CUA 保底</span>
				</div>
			</section>

			<section className="feishu-setup-card" aria-labelledby="feishu-setup-title">
				<div>
					<p className="section-kicker">Feishu AppLink</p>
					<h2 id="feishu-setup-title">可作为飞书网页应用入口</h2>
					<p>
						把部署后的 HTTPS 地址填入飞书开放平台的“网页应用 / 侧边栏入口”，当前页面会自动适配飞书客户端容器。
					</p>
				</div>
				<dl className="runtime-grid">
					<div>
						<dt>运行容器</dt>
						<dd>{feishuConfig.isInFeishuClient ? "飞书客户端" : "浏览器预览"}</dd>
					</div>
					<div>
						<dt>前端入口</dt>
						<dd>{feishuConfig.entryUrl}</dd>
					</div>
					<div>
						<dt>后端 API</dt>
						<dd>{feishuConfig.apiBaseUrl}</dd>
					</div>
				</dl>
			</section>

			<div className="layout-grid">
				<CommandComposer />
				<ExecutionFeed />
				<StatusTimeline />
				<ResultDetail />
			</div>
		</main>
	);
}
