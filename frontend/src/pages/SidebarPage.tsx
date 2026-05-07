import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DebugTracePanel } from "../components/status/DebugTracePanel";
import { RuntimeCheckPanel } from "../components/status/RuntimeCheckPanel";
import { useExecutionStream } from "../features/execution/useExecutionStream";
import {
	cancelExecution,
	cancelLarkCliAccountSetup,
	executeAgentCommand,
	getExecutionDetail,
	getFeishuRuntimeConfig,
	getLarkCliAccount,
	getLarkCliAccountSetup,
	getRuntimeCheck,
	installLarkCli,
	probeQwenModels,
	startLarkCliAccountSetup,
	updateRuntimeConfig,
} from "../lib/api";
import {
	buildDebugTrace,
	buildDetailItems,
	buildTaskCards,
	buildTimelineSteps,
	isTerminalExecutionStatus,
	mergeStreamEvent,
	type ExecutionViewState,
} from "../state/executionStore";
import type {
	ExecuteCommandResponse,
	ExecutionDetailResponse,
	ExecutionStatus,
	ExecutionStreamEvent,
	LarkCliAccountCheck,
	LarkCliAccountSetupJob,
	LarkCliAccountSetupPayload,
	QwenModelProbePayload,
	QwenModelProbeResponse,
	RuntimeCheckResponse,
	RuntimeConfigPayload,
} from "../types/execution";

const SESSION_ID = "demo-session";
const USER_ID = "demo-user";
const DEFAULT_MESSAGE = "给梅家济发消息：“hello”";
const maxSavedHistoryItems = 60;

type ChatTurn = {
	id: string;
	role: "user" | "assistant";
	content: string;
	createdAt: string;
	historyId?: string;
	taskId?: string;
};

type HistoryItem = {
	id: string;
	title: string;
	description: string;
	status: string;
	updatedAt: string;
	prompt: string;
	response?: ExecuteCommandResponse | null;
	detail?: ExecutionDetailResponse | null;
};

export function SidebarPage() {
	const feishuConfig = getFeishuRuntimeConfig();
	const [message, setMessage] = useState(DEFAULT_MESSAGE);
	const [loading, setLoading] = useState(false);
	const [response, setResponse] = useState<ExecuteCommandResponse | null>(null);
	const [detail, setDetail] = useState<ExecutionDetailResponse | null>(null);
	const [lastEvent, setLastEvent] = useState<ExecutionStreamEvent | null>(null);
	const [error, setError] = useState("");
	const [traceQuery, setTraceQuery] = useState("");
	const [runtimeCheck, setRuntimeCheck] = useState<RuntimeCheckResponse | null>(null);
	const [runtimeLoading, setRuntimeLoading] = useState(false);
	const [runtimeSaving, setRuntimeSaving] = useState(false);
	const [larkCliBusy, setLarkCliBusy] = useState(false);
	const [larkAccountBusy, setLarkAccountBusy] = useState(false);
	const [modelProbeBusy, setModelProbeBusy] = useState(false);
	const [qwenModelProbe, setQwenModelProbe] = useState<QwenModelProbeResponse | null>(null);
	const [larkAccount, setLarkAccount] = useState<LarkCliAccountCheck | null>(null);
	const [larkSetupJob, setLarkSetupJob] = useState<LarkCliAccountSetupJob | null>(null);
	const [runtimeError, setRuntimeError] = useState("");
	const [runtimeMessage, setRuntimeMessage] = useState("");
	const [settingsOpen, setSettingsOpen] = useState(false);
	const [activeHistoryId, setActiveHistoryId] = useState("");
	const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
	const [expandedHistoryIds, setExpandedHistoryIds] = useState<string[]>([]);
	const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
	const chatEndRef = useRef<HTMLDivElement | null>(null);
	const chatTurnRefs = useRef<Record<string, HTMLElement | null>>({});

	const handleStreamEvent = useCallback((event: ExecutionStreamEvent) => {
		setLastEvent(event);
		setDetail((currentDetail) => mergeStreamEvent(currentDetail, event));
	}, []);

	const handleStreamDetail = useCallback((nextDetail: ExecutionDetailResponse) => {
		setDetail(nextDetail);
	}, []);

	const currentStatus = detail?.status ?? response?.execution_status ?? response?.initial_status ?? "queued";

	const streamState = useExecutionStream({
		taskId: response?.task_id ?? "",
		enabled: Boolean(response) && !isTerminalExecutionStatus(currentStatus),
		onEvent: handleStreamEvent,
		onDetail: handleStreamDetail,
	});

	const viewState = useMemo<ExecutionViewState | null>(() => {
		if (!response) {
			return null;
		}
		return {
			taskId: response.task_id,
			response,
			detail,
			lastEvent,
			streamConnected: streamState.connected,
			streamError: streamState.error,
		};
	}, [detail, lastEvent, response, streamState.connected, streamState.error]);

	const tasks = useMemo(() => buildTaskCards(viewState), [viewState]);
	const timelineSteps = useMemo(() => buildTimelineSteps(viewState), [viewState]);
	const detailItems = useMemo<[string, string][]>(() => buildDetailItems(viewState), [viewState]);
	const traceItems = useMemo(() => buildDebugTrace(viewState), [viewState]);
	const canCancel = Boolean(response) && !isTerminalExecutionStatus(currentStatus);
	const refreshRuntimeCheck = useCallback(async () => {
		setRuntimeLoading(true);
		setRuntimeError("");
		try {
			const result = await getRuntimeCheck();
			setRuntimeCheck(result);
		} catch (runtimeCheckError) {
			setRuntimeError(runtimeCheckError instanceof Error ? runtimeCheckError.message : "环境检测失败");
		} finally {
			setRuntimeLoading(false);
		}
	}, []);

	const refreshLarkAccount = useCallback(async () => {
		setLarkAccountBusy(true);
		setRuntimeError("");
		try {
			const result = await getLarkCliAccount();
			setLarkAccount(result);
		} catch (accountError) {
			setRuntimeError(accountError instanceof Error ? accountError.message : "飞书帐号检测失败");
		} finally {
			setLarkAccountBusy(false);
		}
	}, []);

	const saveRuntimeConfig = useCallback(async (payload: RuntimeConfigPayload) => {
		setRuntimeSaving(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await updateRuntimeConfig(payload);
			setRuntimeCheck(result.detail);
			const updated = result.updated_keys.length > 0 ? result.updated_keys.join(", ") : "没有字段变化";
			setRuntimeMessage(`已保存：${updated}`);
		} catch (saveError) {
			setRuntimeError(saveError instanceof Error ? saveError.message : "保存配置失败");
		} finally {
			setRuntimeSaving(false);
		}
	}, []);

	const downloadLarkCli = useCallback(async () => {
		setLarkCliBusy(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await installLarkCli({
				package_name: "@larksuite/cli",
				registry_url: "",
			});
			setRuntimeCheck(result.detail);
			setRuntimeMessage(result.message);
			void refreshLarkAccount();
		} catch (installError) {
			setRuntimeError(installError instanceof Error ? installError.message : "lark-cli 下载失败");
		} finally {
			setLarkCliBusy(false);
		}
	}, [refreshLarkAccount]);

	const probeModels = useCallback(async (payload: QwenModelProbePayload) => {
		setModelProbeBusy(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await probeQwenModels(payload);
			setQwenModelProbe(result);
			setRuntimeMessage(`${result.message} 当前选择：${result.selected_model || "未选择"}`);
		} catch (probeError) {
			setQwenModelProbe(null);
			setRuntimeError(probeError instanceof Error ? probeError.message : "模型检测失败");
		} finally {
			setModelProbeBusy(false);
		}
	}, []);

	const startAccountSetup = useCallback(async (payload: LarkCliAccountSetupPayload) => {
		setLarkAccountBusy(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await startLarkCliAccountSetup(payload);
			setLarkSetupJob(result);
			setRuntimeMessage("已启动飞书帐号自动配置，请打开授权链接完成确认。");
		} catch (setupError) {
			setRuntimeError(setupError instanceof Error ? setupError.message : "飞书帐号配置启动失败");
		} finally {
			setLarkAccountBusy(false);
		}
	}, []);

	const cancelAccountSetup = useCallback(async (jobId: string) => {
		setLarkAccountBusy(true);
		setRuntimeError("");
		try {
			const result = await cancelLarkCliAccountSetup(jobId);
			setLarkSetupJob(result);
			setRuntimeMessage("已取消飞书帐号配置流程。");
		} catch (cancelError) {
			setRuntimeError(cancelError instanceof Error ? cancelError.message : "取消飞书帐号配置失败");
		} finally {
			setLarkAccountBusy(false);
		}
	}, []);

	useEffect(() => {
		void refreshRuntimeCheck();
		void refreshLarkAccount();
	}, [refreshLarkAccount, refreshRuntimeCheck]);

	useEffect(() => {
		if (!larkSetupJob || larkSetupJob.status !== "running") {
			return undefined;
		}
		const timer = window.setInterval(() => {
			void getLarkCliAccountSetup(larkSetupJob.job_id)
				.then((result) => {
					setLarkSetupJob(result);
					if (result.status !== "running") {
						if (result.account) {
							setLarkAccount(result.account);
						}
						void refreshRuntimeCheck();
						void refreshLarkAccount();
						setRuntimeMessage(result.message);
					}
				})
				.catch((pollError) => {
					setRuntimeError(pollError instanceof Error ? pollError.message : "飞书帐号配置状态刷新失败");
				});
		}, 2000);
		return () => window.clearInterval(timer);
	}, [larkSetupJob, refreshLarkAccount, refreshRuntimeCheck]);

	useEffect(() => {
		if (!response || !activeHistoryId) {
			return;
		}
		const responseTaskId = response.task_id;
		const updatedAt = formatClock(new Date());
		const description =
			detail?.executor_result?.summary ||
			response.execution_summary ||
			response.intent_reason ||
			"";
		setHistoryItems((items) =>
			items.map((item) =>
				item.response?.task_id === responseTaskId || (!item.response && item.id === activeHistoryId)
					? {
							...item,
							response,
							detail,
							status: statusText(currentStatus),
							description: description || item.description,
							updatedAt,
						}
					: item,
			),
		);
		setChatTurns((turns) =>
			turns.map((turn) =>
				turn.role === "assistant" && turn.taskId === responseTaskId
					? { ...turn, content: persistedAssistantContent(currentStatus, response, detail) }
					: turn,
			),
		);
	}, [activeHistoryId, currentStatus, detail, response]);

	useEffect(() => {
		chatEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
	}, [chatTurns.length]);

	async function submitCommand(messageOverride = "", appendUserTurn = true) {
		const nextMessage = (messageOverride || message).trim();
		if (!nextMessage) {
			return;
		}
		const now = formatClock(new Date());
		const nextHistoryId = makeId("chat");
		setLoading(true);
		setError("");
		if (appendUserTurn) {
			setActiveHistoryId(nextHistoryId);
			setResponse(null);
			setDetail(null);
			setLastEvent(null);
			appendTurn({ role: "user", content: nextMessage, createdAt: now, historyId: nextHistoryId });
			setHistoryItems((items) => [
				{
					id: nextHistoryId,
					title: titleFromPrompt(nextMessage),
					description: nextMessage,
					status: "提交中",
					updatedAt: now,
					prompt: nextMessage,
				},
				...items.filter((item) => item.id !== nextHistoryId).slice(0, maxSavedHistoryItems - 1),
			]);
			setExpandedHistoryIds((ids) => [nextHistoryId, ...ids.filter((id) => id !== nextHistoryId)].slice(0, 12));
		}
		try {
			const result = await executeAgentCommand({
				message: nextMessage,
				session_id: SESSION_ID,
				user_id: USER_ID,
			});
			setResponse(result);
			setDetail(null);
			setLastEvent(null);
			appendTurn({
				role: "assistant",
				content: result.execution_summary || result.intent_reason || "任务已受理，正在跟踪执行状态。",
				createdAt: formatClock(new Date()),
				historyId: nextHistoryId,
				taskId: result.task_id,
			});
			setHistoryItems((items) =>
				items.map((item) =>
					item.id === nextHistoryId
						? {
								...item,
								status: statusText(result.execution_status),
								description: result.execution_summary || result.intent_reason || item.description,
								response: result,
								updatedAt: formatClock(new Date()),
							}
						: item,
				),
			);
		} catch (submitError) {
			const nextError = submitError instanceof Error ? submitError.message : "提交失败";
			setError(nextError);
			appendTurn({
				role: "assistant",
				content: nextError,
				createdAt: formatClock(new Date()),
				historyId: nextHistoryId,
			});
			setHistoryItems((items) =>
				items.map((item) =>
					item.id === nextHistoryId
						? { ...item, status: "失败", description: nextError, updatedAt: formatClock(new Date()) }
						: item,
				),
			);
		} finally {
			setLoading(false);
		}
	}

	async function refreshDetail() {
		if (!response) {
			return;
		}
		setLoading(true);
		setError("");
		try {
			const nextDetail = await getExecutionDetail(response.task_id);
			setDetail(nextDetail);
		} catch (refreshError) {
			setError(refreshError instanceof Error ? refreshError.message : "刷新失败");
		} finally {
			setLoading(false);
		}
	}

	async function retryCurrentCommand() {
		const retryMessage = detail?.raw_message || response?.structured_payload.raw_message?.toString() || message;
		await submitCommand(retryMessage);
	}

	async function cancelCurrentTask() {
		if (!response || !canCancel) {
			return;
		}
		setLoading(true);
		setError("");
		try {
			const result = await cancelExecution(response.task_id);
			setDetail(result.detail);
		} catch (cancelError) {
			setError(cancelError instanceof Error ? cancelError.message : "取消失败");
		} finally {
			setLoading(false);
		}
	}

	function appendTurn(turn: Omit<ChatTurn, "id">) {
		setChatTurns((current) => [...current, { ...turn, id: makeId(turn.role) }]);
	}

	function openHistoryItem(item: HistoryItem) {
		setActiveHistoryId(item.id);
		setExpandedHistoryIds((ids) =>
			activeHistoryId === item.id && ids.includes(item.id)
				? ids.filter((id) => id !== item.id)
				: [item.id, ...ids.filter((id) => id !== item.id)],
		);
		setMessage(item.prompt);
		setError("");
		setResponse(item.response ?? null);
		setDetail(item.detail ?? null);
		setLastEvent(null);
		window.requestAnimationFrame(() => {
			chatTurnRefs.current[item.id]?.scrollIntoView({ block: "center", behavior: "smooth" });
		});
	}

	return (
		<main className={`workspace-layout ${settingsOpen ? "workspace-layout--settings-open" : ""}`}>
			<aside className="history-sidebar" aria-label="消息记录">
				<div className="brand-block">
					<div className="brand-mark">FS</div>
					<div>
						<strong>{feishuConfig.appName}</strong>
						<span>飞书智能执行体</span>
					</div>
				</div>
				<div className="history-section">
					<div className="history-tree-header">
						<span>消息记录</span>
						<small>{historyItems.length} 条</small>
					</div>
					<div className="history-list">
						{historyItems.length === 0 ? <p className="empty-state">还没有消息记录。</p> : null}
						{historyItems.map((item) => (
							<HistoryTreeItem
								key={item.id}
								item={item}
								active={activeHistoryId === item.id}
								expanded={expandedHistoryIds.includes(item.id)}
								onOpen={() => openHistoryItem(item)}
							/>
						))}
					</div>
				</div>
			</aside>

			<section className="chat-panel" aria-label="对话界面">
				<div className="chat-stream" aria-live="polite">
					{chatTurns.length === 0 ? <WelcomePanel /> : null}

					{chatTurns.map((turn) => (
						<ChatBubble
							key={turn.id}
							turn={turn}
							isLiveTask={Boolean(turn.taskId && response?.task_id === turn.taskId)}
							isActive={Boolean(turn.historyId && turn.historyId === activeHistoryId)}
							response={response}
							currentStatus={currentStatus}
							timelineSteps={timelineSteps}
							detailItems={detailItems}
							traceItems={traceItems}
							traceQuery={traceQuery}
							error={error}
							tasks={tasks}
							canCancel={canCancel}
							loading={loading}
							onTraceQueryChange={setTraceQuery}
							onRefresh={() => void refreshDetail()}
							onRetry={() => void retryCurrentCommand()}
							onCancel={() => void cancelCurrentTask()}
							turnRef={(node) => {
								if (turn.historyId && turn.role === "user") {
									chatTurnRefs.current[turn.historyId] = node;
								}
							}}
						/>
					))}

					{loading ? (
						<div className="chat-turn chat-turn--assistant">
							<div className="message-avatar">AI</div>
							<div className="message-stack">
								<div className="thinking-row">
									<span />
									<span />
									<span />
								</div>
							</div>
						</div>
					) : null}
					<div ref={chatEndRef} />
				</div>

				<form
					className="chat-composer"
					onSubmit={(event) => {
						event.preventDefault();
						void submitCommand();
					}}
				>
					<div className="composer-box">
						<button type="button" className="composer-icon-button" onClick={() => setMessage("")} disabled={loading}>
							清空
						</button>
						<label className="sr-only" htmlFor="agent-command-input">
							自然语言指令
						</label>
						<textarea
							id="agent-command-input"
							rows={1}
							value={message}
							placeholder="给飞书助手发送一条任务..."
							disabled={loading}
							onChange={(event) => setMessage(event.target.value)}
							onKeyDown={(event) => {
								if (event.key === "Enter" && !event.shiftKey) {
									event.preventDefault();
									void submitCommand();
								}
							}}
						/>
						<button type="submit" className="send-button" disabled={loading || !message.trim()}>
							{loading ? "..." : "发送"}
						</button>
					</div>
				</form>
			</section>

			<aside className={`settings-sidebar ${settingsOpen ? "settings-sidebar--open" : ""}`} aria-label="环境配置">
				<button
					type="button"
					className="settings-collapse-button"
					aria-expanded={settingsOpen}
					aria-label={settingsOpen ? "折叠环境配置" : "展开环境配置"}
					onClick={() => setSettingsOpen((open) => !open)}
				>
					<span aria-hidden="true">{settingsOpen ? "›" : "‹"}</span>
				</button>
				<div className="settings-sidebar-content" aria-hidden={!settingsOpen}>
					<RuntimeCheckPanel
						data={runtimeCheck}
						loading={runtimeLoading}
						saving={runtimeSaving}
						cliBusy={larkCliBusy}
						accountBusy={larkAccountBusy}
						modelBusy={modelProbeBusy}
						error={runtimeError}
						message={runtimeMessage}
						modelProbe={qwenModelProbe}
						account={larkAccount}
						setupJob={larkSetupJob}
						onRefresh={() => void refreshRuntimeCheck()}
						onSave={(payload) => void saveRuntimeConfig(payload)}
						onProbeModels={(payload) => void probeModels(payload)}
						onInstallLarkCli={() => void downloadLarkCli()}
						onRefreshAccount={() => void refreshLarkAccount()}
						onStartAccountSetup={(payload) => void startAccountSetup(payload)}
						onCancelAccountSetup={(jobId) => void cancelAccountSetup(jobId)}
					/>
				</div>
			</aside>
		</main>
	);
}

function WelcomePanel() {
	return (
		<div className="welcome-panel">
			<h2>想要飞书助手做什么？</h2>
		</div>
	);
}

function HistoryTreeItem({
	item,
	active,
	expanded,
	onOpen,
}: {
	item: HistoryItem;
	active: boolean;
	expanded: boolean;
	onOpen: () => void;
}) {
	const steps = buildHistoryTimelineSteps(item);

	return (
		<div className={`history-tree-item ${active ? "history-tree-item--active" : ""}`}>
			<div className="history-tree-row">
				<span className={`history-node-dot history-node-dot--${statusTone(item.status)}`} aria-hidden="true" />
				<button type="button" className="history-node-main" aria-expanded={expanded} onClick={onOpen}>
					<span className="history-node-title">{item.title}</span>
					<small>{item.status} · {item.updatedAt}</small>
				</button>
			</div>
			{expanded ? <HistoryStatusTree steps={steps} onOpen={onOpen} /> : null}
		</div>
	);
}

function HistoryStatusTree({
	steps,
	onOpen,
}: {
	steps: ReturnType<typeof buildTimelineSteps>;
	onOpen: () => void;
}) {
	return (
		<div className="history-tree-children">
			{steps.map((step) => (
				<button type="button" className={`history-child-node history-child-node--${step.status}`} key={step.id} onClick={onOpen}>
					<span className="history-child-dot" />
					<span>
						<strong>{step.label}</strong>
						<small>{step.detail}</small>
					</span>
				</button>
			))}
		</div>
	);
}

function HorizontalStatusFlow({ steps }: { steps: ReturnType<typeof buildTimelineSteps> }) {
	return (
		<section className="stream-card horizontal-flow-panel" aria-labelledby="horizontal-flow-title">
			<div className="stream-card-title">
				<h2 id="horizontal-flow-title">状态流</h2>
				<span>Live</span>
			</div>
			<ol className="horizontal-flow-list">
				{steps.map((step) => (
					<li className={`horizontal-flow-step horizontal-flow-step--${step.status}`} key={step.id}>
						<span className="horizontal-flow-dot" aria-hidden="true" />
						<div>
							<strong>{step.label}</strong>
							<p>{step.detail}</p>
						</div>
					</li>
				))}
			</ol>
		</section>
	);
}

function ChatBubble({
	turn,
	isLiveTask,
	isActive,
	response,
	currentStatus,
	timelineSteps,
	detailItems,
	traceItems,
	traceQuery,
	error,
	tasks,
	canCancel,
	loading,
	onTraceQueryChange,
	onRefresh,
	onRetry,
	onCancel,
	turnRef,
}: {
	turn: ChatTurn;
	isLiveTask: boolean;
	isActive: boolean;
	response: ExecuteCommandResponse | null;
	currentStatus: ExecutionStatus;
	timelineSteps: ReturnType<typeof buildTimelineSteps>;
	detailItems: [string, string][];
	traceItems: ReturnType<typeof buildDebugTrace>;
	traceQuery: string;
	error: string;
	tasks: ReturnType<typeof buildTaskCards>;
	canCancel: boolean;
	loading: boolean;
	onTraceQueryChange: (value: string) => void;
	onRefresh: () => void;
	onRetry: () => void;
	onCancel: () => void;
	turnRef: (node: HTMLElement | null) => void;
}) {
	const isLiveAssistantTurn = turn.role === "assistant" && isLiveTask;
	const assistantMessage = isLiveAssistantTurn
		? liveAssistantMessage(currentStatus, error)
		: turn.content;
	const showStreamIndicator =
		isLiveAssistantTurn &&
		currentStatus !== "completed" &&
		currentStatus !== "failed" &&
		currentStatus !== "cli_failed" &&
		currentStatus !== "canceled";

	return (
		<article className={`chat-turn chat-turn--${turn.role} ${isActive ? "chat-turn--active" : ""}`} ref={turnRef}>
			<div className="message-avatar">{turn.role === "user" ? "你" : "AI"}</div>
			<div className="message-stack">
				<div
					className={`message-bubble ${
						isLiveAssistantTurn ? `message-bubble--live message-bubble--${currentStatus}` : ""
					}`}
				>
					<p>
						{assistantMessage}
						{showStreamIndicator ? (
							<span className="streaming-dots" aria-hidden="true">
								<span />
								<span />
								<span />
							</span>
						) : null}
						{isLiveAssistantTurn ? <span className="stream-cursor" aria-hidden="true" /> : null}
					</p>
					<time>{turn.createdAt}</time>
				</div>

				{isLiveTask && response ? (
					<div className="assistant-workspace">
						<HorizontalStatusFlow steps={timelineSteps} />
						{error ? <p className="error-banner">{error}</p> : null}
						<details className="assistant-more-panel trace-collapse-panel">
							<summary>轨迹面板</summary>
							<DebugTracePanel items={traceItems} query={traceQuery} onQueryChange={onTraceQueryChange} />
						</details>
						<details className="assistant-more-panel">
							<summary>更多执行信息</summary>
							<div className="assistant-more-actions">
								<button type="button" className="secondary-button" disabled={loading || !response} onClick={onRefresh}>
									刷新
								</button>
								<button type="button" className="secondary-button" disabled={loading || !canCancel} onClick={onCancel}>
									取消
								</button>
								<button type="button" className="primary-button" disabled={loading || !response} onClick={onRetry}>
									重试
								</button>
							</div>
							<div className="assistant-more-grid">
								<div>
									<span>当前状态</span>
									<strong>{statusText(currentStatus)}</strong>
								</div>
								{tasks.map((task) => (
									<div key={task.id}>
										<span>{task.owner} · {task.duration}</span>
										<strong>{task.title}</strong>
									</div>
								))}
								{detailItems.slice(0, 6).map(([label, value]) => (
									<div key={label}>
										<span>{label}</span>
										<strong>{value}</strong>
									</div>
								))}
							</div>
						</details>
					</div>
				) : null}
			</div>
		</article>
	);
}

function makeId(prefix: string): string {
	const randomId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
	return `${prefix}-${randomId}`;
}

function titleFromPrompt(prompt: string): string {
	const trimmed = prompt.replace(/\s+/g, " ").trim();
	return trimmed.length > 18 ? `${trimmed.slice(0, 18)}...` : trimmed || "新对话";
}

function buildHistoryTimelineSteps(item: HistoryItem): ReturnType<typeof buildTimelineSteps> {
	if (!item.response) {
		return [
			{
				id: "draft",
				label: "用户消息",
				detail: item.prompt,
				status: "done",
			},
			{
				id: "waiting",
				label: "等待执行",
				detail: "尚未生成任务状态。",
				status: "pending",
			},
		];
	}
	return buildTimelineSteps({
		taskId: item.response.task_id,
		response: item.response,
		detail: item.detail ?? null,
		lastEvent: null,
		streamConnected: false,
		streamError: "",
	});
}

function statusTone(status: string): "running" | "success" | "danger" | "idle" {
	if (status.includes("完成")) {
		return "success";
	}
	if (status.includes("失败") || status.includes("取消")) {
		return "danger";
	}
	if (status.includes("中") || status.includes("接管") || status.includes("排队")) {
		return "running";
	}
	return "idle";
}

function liveAssistantMessage(status: ExecutionStatus, error: string): string {
	if (error) {
		return error;
	}
	if (status === "completed") {
		return "完成！";
	}
	if (status === "failed" || status === "cli_failed") {
		return "执行失败";
	}
	if (status === "canceled") {
		return "已取消";
	}
	const labels: Record<ExecutionStatus, string> = {
		queued: "已收到，正在排队",
		parsing: "正在理解任务",
		cli_running: "正在通过 CLI 执行",
		cli_failed: "执行失败",
		cua_running: "正在接管桌面操作",
		completed: "完成！",
		failed: "执行失败",
		canceled: "已取消",
	};
	return labels[status];
}

function persistedAssistantContent(
	status: ExecutionStatus,
	response: ExecuteCommandResponse,
	detail: ExecutionDetailResponse | null,
): string {
	const summary = detail?.executor_result?.summary || response.execution_summary || response.intent_reason || "";
	if (status === "completed") {
		return "完成！";
	}
	if (status === "failed" || status === "cli_failed" || status === "canceled") {
		return liveAssistantMessage(status, "");
	}
	return liveAssistantMessage(status, "") || summary || "任务已受理，状态将通过长连接持续更新。";
}

function formatClock(value: Date): string {
	return value.toLocaleTimeString("zh-CN", {
		hour: "2-digit",
		minute: "2-digit",
	});
}

function statusText(status: ExecutionStatus): string {
	const labels: Record<ExecutionStatus, string> = {
		queued: "排队中",
		parsing: "解析中",
		cli_running: "CLI 执行中",
		cli_failed: "CLI 失败",
		cua_running: "CUA 接管中",
		completed: "已完成",
		failed: "失败",
		canceled: "已取消",
	};
	return labels[status];
}
