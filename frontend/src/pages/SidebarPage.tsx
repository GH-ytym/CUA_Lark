import { useMemo, useState } from "react";
import { CommandComposer } from "../components/chat/CommandComposer";
import { ExecutionFeed } from "../components/chat/ExecutionFeed";
import { ResultDetail } from "../components/status/ResultDetail";
import { StatusTimeline } from "../components/status/StatusTimeline";
import { executeAgentCommand, getFeishuRuntimeConfig } from "../lib/api";
import type { ExecuteCommandResponse, ResolutionCandidate, TaskCard, TimelineStep } from "../types/execution";

const SESSION_ID = "demo-session";
const USER_ID = "demo-user";

export function SidebarPage() {
	const feishuConfig = getFeishuRuntimeConfig();
	const [message, setMessage] = useState("");
	const [loading, setLoading] = useState(false);
	const [response, setResponse] = useState<ExecuteCommandResponse | null>(null);
	const [error, setError] = useState("");
	const [selectedCandidateId, setSelectedCandidateId] = useState("");

	const tasks = useMemo<TaskCard[]>(() => {
		if (!response) {
			return [];
		}
		const baseDescription = response.needs_confirmation
			? response.confirmation_message || "等待你确认发送对象。"
			: response.intent_reason || "任务已受理。";
		return [
			{
				id: response.task_id,
				title: response.needs_confirmation ? "待确认发送对象" : "任务已受理",
				description: baseDescription,
				status: response.needs_confirmation ? "queued" : "running",
				owner:
					response.selected_executor === "cli"
						? "CLI"
						: response.selected_executor === "cua"
							? "CUA"
							: "Agent",
				duration: response.parse_source || "-",
			},
		];
	}, [response]);

	const timelineSteps = useMemo<TimelineStep[]>(() => {
		const hasResponse = Boolean(response);
		const waitingConfirmation = Boolean(response?.needs_confirmation);
		return [
			{
				id: "parse",
				label: "解析",
				detail: hasResponse ? `来源：${response?.parse_source || "unknown"}` : "识别意图与消息实体",
				status: hasResponse ? "done" : "active",
			},
			{
				id: "resolve",
				label: "解析对象",
				detail: waitingConfirmation ? "已给出候选，等待你确认" : "优先走本地匹配，必要时才调用 LLM",
				status: waitingConfirmation ? "active" : hasResponse ? "done" : "pending",
			},
			{
				id: "confirm",
				label: "确认",
				detail: waitingConfirmation ? "前端二次确认后继续执行" : "高置信直接通过，灰区走确认",
				status: waitingConfirmation ? "active" : hasResponse ? "done" : "pending",
			},
			{
				id: "execute",
				label: "执行",
				detail: waitingConfirmation ? "确认完成后可继续发消息" : "当前版本先返回受理结果与结构化载荷",
				status: hasResponse && !waitingConfirmation ? "active" : "pending",
			},
		];
	}, [response]);

	const detailItems = useMemo<[string, string][]>(() => {
		if (!response) {
			return [
				["当前状态", "尚未提交任务"],
				["优化目标", "先本地 resolve，再按需调用 LLM"],
				["交互策略", "命中灰区时前端确认后继续"],
				["当前能力", "消息发送优先验证"],
			];
		}
		return [
			["任务 ID", response.task_id],
			["意图", response.parsed_intent],
			["原因", response.intent_reason || "-"],
			["结构化载荷", JSON.stringify(response.structured_payload)],
		];
	}, [response]);

	const candidates = response?.resolution_candidates ?? [];

	async function submitCommand(confirmedEntityId = "") {
		const nextMessage = message.trim();
		if (!nextMessage) {
			return;
		}
		setLoading(true);
		setError("");
		try {
			const result = await executeAgentCommand({
				message: nextMessage,
				session_id: SESSION_ID,
				user_id: USER_ID,
				confirmed_entity_id: confirmedEntityId,
			});
			setResponse(result);
			if (result.needs_confirmation) {
				setSelectedCandidateId(result.resolution_candidates[0]?.entity_id ?? "");
			} else {
				setSelectedCandidateId("");
			}
		} catch (submitError) {
			const nextError = submitError instanceof Error ? submitError.message : "提交失败";
			setError(nextError);
		} finally {
			setLoading(false);
		}
	}

	async function handleConfirmCandidate() {
		if (!selectedCandidateId) {
			return;
		}
		await submitCommand(selectedCandidateId);
	}

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
				<CommandComposer value={message} disabled={loading} onChange={setMessage} onSubmit={() => void submitCommand()} />
				<ExecutionFeed tasks={tasks} />
				<StatusTimeline steps={timelineSteps} />
				<ResultDetail title={response?.needs_confirmation ? "待确认详情" : "解析详情"} items={detailItems} />
			</div>

			<section className="panel confirmation-panel" aria-labelledby="confirmation-title">
				<div className="panel-title-row">
					<div>
						<p className="section-kicker">05 · 二次确认</p>
						<h2 id="confirmation-title">候选选择</h2>
					</div>
					<span className="wire-tag">Confirm</span>
				</div>
				{error ? <p className="error-banner">{error}</p> : null}
				{response?.needs_confirmation ? (
					<>
						<p className="confirmation-tip">{response.confirmation_message}</p>
						<div className="candidate-list" role="list">
							{candidates.map((candidate: ResolutionCandidate) => (
								<label className="candidate-card" key={candidate.entity_id}>
									<input
										type="radio"
										name="candidate"
										value={candidate.entity_id}
										checked={selectedCandidateId === candidate.entity_id}
										onChange={() => setSelectedCandidateId(candidate.entity_id)}
									/>
									<div>
										<strong>{candidate.name}</strong>
										<p>
											{candidate.entity_type} · score {candidate.score.toFixed(4)}
										</p>
									</div>
								</label>
							))}
						</div>
						<div className="composer-actions">
							<button type="button" className="primary-button" disabled={loading || !selectedCandidateId} onClick={() => void handleConfirmCandidate()}>
								确认对象并继续
							</button>
						</div>
					</>
				) : (
					<p className="empty-state">当对象解析进入灰区时，这里会展示候选人或群聊供你确认。</p>
				)}
			</section>
		</main>
	);
}
