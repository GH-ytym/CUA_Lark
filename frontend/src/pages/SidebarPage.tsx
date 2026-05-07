import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DebugTracePanel } from "../components/status/DebugTracePanel";
import { ErrorState } from "../components/status/ErrorState";
import { ResultDetail } from "../components/status/ResultDetail";
import { RuntimeCheckPanel } from "../components/status/RuntimeCheckPanel";
import { StatusTimeline } from "../components/status/StatusTimeline";
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
	buildIssueSummary,
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
const historyStorageKey = "cua-lark.chat-history.v1";
const maxSavedHistoryItems = 60;

const quickCommands = [
	"给梅家济发消息：“hello”",
	"给项目群发今晚发布窗口提醒",
	"创建明天 10:00 的飞书会议并邀请项目组",
	"把今天的联调结论整理成飞书文档",
];

type ChatTurn = {
	id: string;
	role: "user" | "assistant";
	content: string;
	createdAt: string;
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
	const [activeHistoryId, setActiveHistoryId] = useState("");
	const [historyItems, setHistoryItems] = useState<HistoryItem[]>(() => readHistoryStorage());
	const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
	const chatEndRef = useRef<HTMLDivElement | null>(null);

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
	const issueSummary = useMemo(() => buildIssueSummary(viewState), [viewState]);
	const canCancel = Boolean(response) && !isTerminalExecutionStatus(currentStatus);
	const liveStatus = useMemo(
		() =>
			buildLiveStatus({
				loading,
				currentStatus,
				response,
				detail,
				streamConnected: streamState.connected,
				streamError: streamState.error,
			}),
		[currentStatus, detail, loading, response, streamState.connected, streamState.error],
	);

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
		setHistoryItems((items) =>
			items.map((item) =>
				item.id === activeHistoryId
					? {
							...item,
							response,
							detail,
							status: statusText(currentStatus),
							description:
								detail?.executor_result?.summary ||
								response.execution_summary ||
								response.intent_reason ||
								item.description,
							updatedAt: formatClock(new Date()),
						}
					: item,
			),
		);
	}, [activeHistoryId, currentStatus, detail, response]);

	useEffect(() => {
		writeHistoryStorage(historyItems.slice(0, maxSavedHistoryItems));
	}, [historyItems]);

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
			appendTurn({ role: "user", content: nextMessage, createdAt: now });
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

	function startNewChat() {
		const id = makeId("draft");
		setActiveHistoryId(id);
		setResponse(null);
		setDetail(null);
		setLastEvent(null);
		setError("");
		setTraceQuery("");
		setMessage("");
		setChatTurns([]);
	}

	function openHistoryItem(item: HistoryItem) {
		setActiveHistoryId(item.id);
		setMessage(item.prompt);
		setError("");
		setResponse(item.response ?? null);
		setDetail(item.detail ?? null);
		setLastEvent(null);
		setChatTurns(rebuildTurns(item));
	}

	function deleteHistoryItem(itemId: string) {
		setHistoryItems((items) => items.filter((item) => item.id !== itemId));
		if (activeHistoryId !== itemId) {
			return;
		}
		setActiveHistoryId("");
		setResponse(null);
		setDetail(null);
		setLastEvent(null);
		setError("");
		setChatTurns([]);
	}

	return (
		<main className="workspace-layout">
			<aside className="history-sidebar" aria-label="历史消息">
				<div className="brand-block">
					<div className="brand-mark">FS</div>
					<div>
						<strong>{feishuConfig.appName}</strong>
						<span>飞书智能执行体</span>
					</div>
				</div>
				<button type="button" className="new-chat-button" onClick={startNewChat}>
					<span aria-hidden="true">+</span>
					新建对话
				</button>
				<div className={`sidebar-live-status sidebar-live-status--${liveStatus.tone}`}>
					<div>
						<span className={`status-dot status-dot--${currentStatus}`} />
						<strong>{liveStatus.title}</strong>
					</div>
					<p>{liveStatus.description}</p>
				</div>
				<div className="history-section">
					<div className="sidebar-caption">历史消息</div>
					<div className="history-list">
						{historyItems.length === 0 ? <p className="empty-state">还没有历史消息。</p> : null}
						{historyItems.map((item) => (
							<div
								className={`history-item ${activeHistoryId === item.id ? "history-item--active" : ""}`}
								key={item.id}
							>
								<button type="button" className="history-item-main" onClick={() => openHistoryItem(item)}>
									<span>{item.title}</span>
									<small>{item.description}</small>
									<em>{item.status} · {item.updatedAt}</em>
								</button>
								<button
									type="button"
									className="history-delete-button"
									aria-label={`删除 ${item.title}`}
									title="删除"
									onClick={() => deleteHistoryItem(item.id)}
								>
									×
								</button>
							</div>
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
							response={response}
							currentStatus={currentStatus}
							timelineSteps={timelineSteps}
							detailItems={detailItems}
							traceItems={traceItems}
							traceQuery={traceQuery}
							issueSummary={issueSummary}
							error={error}
							tasks={tasks}
							canCancel={canCancel}
							loading={loading}
							onTraceQueryChange={setTraceQuery}
							onRefresh={() => void refreshDetail()}
							onRetry={() => void retryCurrentCommand()}
							onCancel={() => void cancelCurrentTask()}
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
					<div className="quick-command-row" aria-label="快捷指令">
						{quickCommands.map((command) => (
							<button type="button" key={command} onClick={() => setMessage(command)} disabled={loading}>
								{command}
							</button>
						))}
					</div>
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

			<aside className="settings-sidebar" aria-label="环境配置">
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
			</aside>
		</main>
	);
}

function WelcomePanel() {
	return (
		<div className="welcome-panel">
			<h2>要让飞书助手做什么？</h2>
		</div>
	);
}

function ChatBubble({
	turn,
	isLiveTask,
	response,
	currentStatus,
	timelineSteps,
	detailItems,
	traceItems,
	traceQuery,
	issueSummary,
	error,
	tasks,
	canCancel,
	loading,
	onTraceQueryChange,
	onRefresh,
	onRetry,
	onCancel,
}: {
	turn: ChatTurn;
	isLiveTask: boolean;
	response: ExecuteCommandResponse | null;
	currentStatus: ExecutionStatus;
	timelineSteps: ReturnType<typeof buildTimelineSteps>;
	detailItems: [string, string][];
	traceItems: ReturnType<typeof buildDebugTrace>;
	traceQuery: string;
	issueSummary: ReturnType<typeof buildIssueSummary>;
	error: string;
	tasks: ReturnType<typeof buildTaskCards>;
	canCancel: boolean;
	loading: boolean;
	onTraceQueryChange: (value: string) => void;
	onRefresh: () => void;
	onRetry: () => void;
	onCancel: () => void;
}) {
	return (
		<article className={`chat-turn chat-turn--${turn.role}`}>
			<div className="message-avatar">{turn.role === "user" ? "你" : "AI"}</div>
			<div className="message-stack">
				<div className="message-bubble">
					<p>{turn.content}</p>
					<time>{turn.createdAt}</time>
				</div>

				{isLiveTask && response ? (
					<div className="assistant-workspace">
						<div className="assistant-summary-card">
							<div>
								<span className={`status-dot status-dot--${currentStatus}`} />
								<strong>{statusText(currentStatus)}</strong>
								<p>{tasks[0]?.description || response.execution_summary || response.intent_reason || "任务执行状态同步中。"}</p>
							</div>
							<div className="summary-actions">
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
						</div>

						{issueSummary ? (
							<ErrorState
								title={issueSummary.title}
								description={issueSummary.description}
								actionHint={issueSummary.actionHint}
								severity={issueSummary.severity}
								onRefresh={onRefresh}
								onRetry={onRetry}
								onCancel={onCancel}
								canCancel={canCancel}
								disabled={loading}
							/>
						) : null}

						{error ? <p className="error-banner">{error}</p> : null}

						<div className="task-strip">
							{tasks.map((task) => (
								<div className={`task-chip task-chip--${task.status}`} key={task.id}>
									<strong>{task.title}</strong>
									<span>{task.owner} · {task.duration}</span>
								</div>
							))}
						</div>

						<div className="assistant-grid">
							<StatusTimeline steps={timelineSteps} />
							<ResultDetail title="执行详情" items={detailItems} />
						</div>
						<DebugTracePanel items={traceItems} query={traceQuery} onQueryChange={onTraceQueryChange} />
					</div>
				) : null}
			</div>
		</article>
	);
}

function rebuildTurns(item: HistoryItem): ChatTurn[] {
	const turns: ChatTurn[] = [
		{
			id: makeId("history-user"),
			role: "user",
			content: item.prompt,
			createdAt: item.updatedAt,
		},
	];
	if (item.response) {
		turns.push({
			id: makeId("history-assistant"),
			role: "assistant",
			content: item.response.execution_summary || item.response.intent_reason || "任务已受理，正在跟踪执行状态。",
			createdAt: item.updatedAt,
			taskId: item.response.task_id,
		});
	}
	return turns;
}

function buildLiveStatus({
	loading,
	currentStatus,
	response,
	detail,
	streamConnected,
	streamError,
}: {
	loading: boolean;
	currentStatus: ExecutionStatus;
	response: ExecuteCommandResponse | null;
	detail: ExecutionDetailResponse | null;
	streamConnected: boolean;
	streamError: string;
}): { title: string; description: string; tone: "idle" | "running" | "success" | "danger" } {
	if (!response) {
		return {
			title: "空闲",
			description: "还没有正在跟踪的任务。",
			tone: "idle",
		};
	}
	if (streamError) {
		return {
			title: "轮询兜底",
			description: streamError,
			tone: "danger",
		};
	}
	const summary = detail?.executor_result?.summary || response.execution_summary || response.intent_reason || "任务状态同步中。";
	if (currentStatus === "completed") {
		return {
			title: "已完成",
			description: summary,
			tone: "success",
		};
	}
	if (currentStatus === "failed" || currentStatus === "cli_failed" || currentStatus === "canceled") {
		return {
			title: statusText(currentStatus),
			description: summary,
			tone: "danger",
		};
	}
	return {
		title: loading ? "提交中" : streamConnected ? "实时连接中" : statusText(currentStatus),
		description: summary,
		tone: "running",
	};
}

function readHistoryStorage(): HistoryItem[] {
	if (typeof window === "undefined") {
		return [];
	}
	try {
		const raw = window.localStorage.getItem(historyStorageKey);
		if (!raw) {
			return [];
		}
		const parsed = JSON.parse(raw) as unknown;
		if (!Array.isArray(parsed)) {
			return [];
		}
		return parsed.filter(isHistoryItem).slice(0, maxSavedHistoryItems);
	} catch {
		return [];
	}
}

function writeHistoryStorage(items: HistoryItem[]) {
	if (typeof window === "undefined") {
		return;
	}
	try {
		window.localStorage.setItem(historyStorageKey, JSON.stringify(items));
	} catch {
		// Local storage can be unavailable in restricted containers.
	}
}

function isHistoryItem(value: unknown): value is HistoryItem {
	if (!value || typeof value !== "object") {
		return false;
	}
	const item = value as Partial<HistoryItem>;
	return (
		typeof item.id === "string" &&
		typeof item.title === "string" &&
		typeof item.description === "string" &&
		typeof item.status === "string" &&
		typeof item.updatedAt === "string" &&
		typeof item.prompt === "string"
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
