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
	enableLarkCli,
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
	LarkCliEnablePayload,
	LarkCliInstallPayload,
	QwenModelProbePayload,
	QwenModelProbeResponse,
	ResolutionCandidate,
	RuntimeCheckResponse,
	RuntimeConfigPayload,
} from "../types/execution";

const SESSION_ID = "demo-session";
const USER_ID = "demo-user";
const DEFAULT_MESSAGE = "给梅家济发消息：“hello”";

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

const starterHistory: HistoryItem[] = [
	{
		id: "starter-message",
		title: "发送飞书消息",
		description: "给梅家济发消息：“hello”",
		status: "示例",
		updatedAt: "刚刚",
		prompt: DEFAULT_MESSAGE,
	},
	{
		id: "starter-calendar",
		title: "预约日程",
		description: "创建明天 10:00 的联调会议",
		status: "示例",
		updatedAt: "今天",
		prompt: "创建明天 10:00 的飞书会议并邀请项目组",
	},
	{
		id: "starter-doc",
		title: "生成文档",
		description: "整理联调结论到飞书文档",
		status: "示例",
		updatedAt: "今天",
		prompt: "把今天的联调结论整理成飞书文档",
	},
];

export function SidebarPage() {
	const feishuConfig = getFeishuRuntimeConfig();
	const [message, setMessage] = useState(DEFAULT_MESSAGE);
	const [loading, setLoading] = useState(false);
	const [response, setResponse] = useState<ExecuteCommandResponse | null>(null);
	const [detail, setDetail] = useState<ExecutionDetailResponse | null>(null);
	const [lastEvent, setLastEvent] = useState<ExecutionStreamEvent | null>(null);
	const [error, setError] = useState("");
	const [selectedCandidateId, setSelectedCandidateId] = useState("");
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
	const [activeHistoryId, setActiveHistoryId] = useState("starter-message");
	const [historyItems, setHistoryItems] = useState<HistoryItem[]>(starterHistory);
	const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);
	const chatEndRef = useRef<HTMLDivElement | null>(null);

	const handleStreamEvent = useCallback((event: ExecutionStreamEvent) => {
		setLastEvent(event);
		setDetail((currentDetail) => mergeStreamEvent(currentDetail, event));
	}, []);

	const handleStreamDetail = useCallback((nextDetail: ExecutionDetailResponse) => {
		setDetail(nextDetail);
	}, []);

	const streamState = useExecutionStream({
		taskId: response?.task_id ?? "",
		enabled: Boolean(response),
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
	const currentStatus = detail?.status ?? response?.execution_status ?? response?.initial_status ?? "queued";
	const canCancel = Boolean(response) && !isTerminalExecutionStatus(currentStatus);
	const candidates = response?.resolution_candidates ?? [];
	const requiredReady = useMemo(() => summarizeRuntime(runtimeCheck), [runtimeCheck]);

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

	const downloadAndEnableLarkCli = useCallback(async (payload: LarkCliInstallPayload) => {
		setLarkCliBusy(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await installLarkCli(payload);
			setRuntimeCheck(result.detail);
			const updated = result.updated_keys.length > 0 ? `，更新 ${result.updated_keys.join(", ")}` : "";
			setRuntimeMessage(`${result.message}${updated}。路径：${result.bin_path}`);
		} catch (installError) {
			setRuntimeError(installError instanceof Error ? installError.message : "lark-cli 下载失败");
		} finally {
			setLarkCliBusy(false);
		}
	}, []);

	const enableExistingLarkCli = useCallback(async (payload: LarkCliEnablePayload) => {
		setLarkCliBusy(true);
		setRuntimeError("");
		setRuntimeMessage("");
		try {
			const result = await enableLarkCli(payload);
			setRuntimeCheck(result.detail);
			const updated = result.updated_keys.length > 0 ? `，更新 ${result.updated_keys.join(", ")}` : "";
			setRuntimeMessage(`${result.message}${updated}。路径：${result.bin_path}`);
		} catch (enableError) {
			setRuntimeError(enableError instanceof Error ? enableError.message : "lark-cli 启用失败");
		} finally {
			setLarkCliBusy(false);
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
		chatEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
	}, [chatTurns.length, detail?.updated_at, lastEvent?.sequence, loading]);

	async function submitCommand(confirmedEntityId = "", messageOverride = "", appendUserTurn = true) {
		const nextMessage = (messageOverride || message).trim();
		if (!nextMessage) {
			return;
		}
		const now = formatClock(new Date());
		const nextHistoryId = confirmedEntityId ? activeHistoryId : makeId("chat");
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
				...items.filter((item) => item.id !== nextHistoryId),
			]);
		}
		try {
			const result = await executeAgentCommand({
				message: nextMessage,
				session_id: SESSION_ID,
				user_id: USER_ID,
				confirmed_entity_id: confirmedEntityId,
			});
			setResponse(result);
			setDetail(null);
			setLastEvent(null);
			appendTurn({
				role: "assistant",
				content: result.needs_confirmation
					? result.confirmation_message
					: result.execution_summary || result.intent_reason || "任务已受理，正在跟踪执行状态。",
				createdAt: formatClock(new Date()),
				taskId: result.task_id,
			});
			if (result.needs_confirmation) {
				setSelectedCandidateId(result.resolution_candidates[0]?.entity_id ?? "");
			} else {
				setSelectedCandidateId("");
			}
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

	async function handleConfirmCandidate() {
		if (!selectedCandidateId) {
			return;
		}
		const candidate = candidates.find((item) => item.entity_id === selectedCandidateId);
		appendTurn({
			role: "user",
			content: `确认对象：${candidate?.name ?? selectedCandidateId}`,
			createdAt: formatClock(new Date()),
		});
		await submitCommand(selectedCandidateId, "", false);
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
		await submitCommand("", retryMessage);
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
		setSelectedCandidateId("");
		setTraceQuery("");
		setMessage("");
		setChatTurns([]);
	}

	function openHistoryItem(item: HistoryItem) {
		setActiveHistoryId(item.id);
		setMessage(item.prompt);
		setError("");
		setSelectedCandidateId("");
		setResponse(item.response ?? null);
		setDetail(item.detail ?? null);
		setLastEvent(null);
		setChatTurns(rebuildTurns(item));
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
				<div className="history-section">
					<div className="sidebar-caption">历史消息</div>
					<div className="history-list">
						{historyItems.map((item) => (
							<button
								type="button"
								className={`history-item ${activeHistoryId === item.id ? "history-item--active" : ""}`}
								key={item.id}
								onClick={() => openHistoryItem(item)}
							>
								<span>{item.title}</span>
								<small>{item.description}</small>
								<em>{item.status} · {item.updatedAt}</em>
							</button>
						))}
					</div>
				</div>
				<div className="sidebar-footer">
					<div>
						<span className={`connection-dot ${runtimeCheck?.ready ? "connection-dot--ready" : ""}`} />
						{runtimeCheck?.ready ? "环境就绪" : "待补配置"}
					</div>
					<small>{feishuConfig.isInFeishuClient ? "飞书客户端" : "浏览器预览"}</small>
				</div>
			</aside>

			<section className="chat-panel" aria-label="对话界面">
				<header className="chat-header">
					<div>
						<p className="eyebrow">CUA-Lark Agent</p>
						<h1>飞书自动化助手</h1>
					</div>
					<div className="chat-header-actions">
						<span className={`status-pill status-pill--${runtimeCheck?.ready ? "ready" : "setup"}`}>
							{runtimeCheck?.ready ? "Ready" : "Setup"}
						</span>
						<span className="status-pill">{response ? statusText(currentStatus) : "待输入"}</span>
					</div>
				</header>

				<div className="chat-stream" aria-live="polite">
					{chatTurns.length === 0 ? (
						<WelcomePanel
							requiredReady={requiredReady}
							apiBaseUrl={feishuConfig.apiBaseUrl}
							onPickPrompt={(prompt) => setMessage(prompt)}
						/>
					) : null}

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
							candidates={candidates}
							selectedCandidateId={selectedCandidateId}
							canCancel={canCancel}
							loading={loading}
							onTraceQueryChange={setTraceQuery}
							onCandidateChange={setSelectedCandidateId}
							onConfirmCandidate={() => void handleConfirmCandidate()}
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
				<div className="settings-overview">
					<div>
						<p className="eyebrow">Runtime</p>
						<h2>环境配置</h2>
					</div>
					<span className={`settings-score ${runtimeCheck?.ready ? "settings-score--ready" : ""}`}>
						{requiredReady.ready}/{requiredReady.total}
					</span>
				</div>
				<div className="settings-mini-grid">
					<div>
						<span>LLM</span>
						<strong>{checkStatus(runtimeCheck, "dashscope_api_key")}</strong>
					</div>
					<div>
						<span>视觉模型</span>
						<strong>{checkStatus(runtimeCheck, "cua_model_api_key")}</strong>
					</div>
					<div>
						<span>CLI</span>
						<strong>{checkStatus(runtimeCheck, "lark_cli")}</strong>
					</div>
					<div>
						<span>飞书授权</span>
						<strong>{checkStatus(runtimeCheck, "lark_cli_auth")}</strong>
					</div>
				</div>
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
					onInstallCli={(payload) => void downloadAndEnableLarkCli(payload)}
					onEnableCli={(payload) => void enableExistingLarkCli(payload)}
					onRefreshAccount={() => void refreshLarkAccount()}
					onStartAccountSetup={(payload) => void startAccountSetup(payload)}
					onCancelAccountSetup={(jobId) => void cancelAccountSetup(jobId)}
				/>
			</aside>
		</main>
	);
}

function WelcomePanel({
	requiredReady,
	apiBaseUrl,
	onPickPrompt,
}: {
	requiredReady: { ready: number; total: number };
	apiBaseUrl: string;
	onPickPrompt: (prompt: string) => void;
}) {
	return (
		<div className="welcome-panel">
			<p className="eyebrow">New Chat</p>
			<h2>要让飞书助手做什么？</h2>
			<div className="welcome-grid">
				<button type="button" onClick={() => onPickPrompt(quickCommands[0])}>
					<strong>发送消息</strong>
					<span>按自然语言找人或群，并通过 lark-cli 执行。</span>
				</button>
				<button type="button" onClick={() => onPickPrompt(quickCommands[2])}>
					<strong>预约会议</strong>
					<span>解析时间、参会人和会议主题。</span>
				</button>
				<button type="button" onClick={() => onPickPrompt(quickCommands[3])}>
					<strong>生成文档</strong>
					<span>把结论沉淀到飞书云文档。</span>
				</button>
			</div>
			<div className="welcome-meta">
				<span>必需配置 {requiredReady.ready}/{requiredReady.total}</span>
				<span>API {apiBaseUrl}</span>
			</div>
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
	candidates,
	selectedCandidateId,
	canCancel,
	loading,
	onTraceQueryChange,
	onCandidateChange,
	onConfirmCandidate,
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
	candidates: ResolutionCandidate[];
	selectedCandidateId: string;
	canCancel: boolean;
	loading: boolean;
	onTraceQueryChange: (value: string) => void;
	onCandidateChange: (value: string) => void;
	onConfirmCandidate: () => void;
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

						{response.needs_confirmation ? (
							<ConfirmationBlock
								candidates={candidates}
								selectedCandidateId={selectedCandidateId}
								loading={loading}
								onCandidateChange={onCandidateChange}
								onConfirmCandidate={onConfirmCandidate}
							/>
						) : null}

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
							<ResultDetail title={response.needs_confirmation ? "待确认详情" : "执行详情"} items={detailItems} />
						</div>
						<DebugTracePanel items={traceItems} query={traceQuery} onQueryChange={onTraceQueryChange} />
					</div>
				) : null}
			</div>
		</article>
	);
}

function ConfirmationBlock({
	candidates,
	selectedCandidateId,
	loading,
	onCandidateChange,
	onConfirmCandidate,
}: {
	candidates: ResolutionCandidate[];
	selectedCandidateId: string;
	loading: boolean;
	onCandidateChange: (value: string) => void;
	onConfirmCandidate: () => void;
}) {
	if (candidates.length === 0) {
		return (
			<div className="confirmation-empty">
				<strong>没有可确认的候选对象</strong>
				<p>请补齐飞书通讯录权限，或直接输入明确的 open_id / chat_id。</p>
				<code>lark-cli auth login --domain im,contact</code>
			</div>
		);
	}
	return (
		<div className="confirmation-panel">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">Confirm</p>
					<h2>选择目标对象</h2>
				</div>
			</div>
			<div className="candidate-list" role="list">
				{candidates.map((candidate) => (
					<label className="candidate-card" key={candidate.entity_id}>
						<input
							type="radio"
							name="candidate"
							value={candidate.entity_id}
							checked={selectedCandidateId === candidate.entity_id}
							onChange={() => onCandidateChange(candidate.entity_id)}
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
				<button type="button" className="primary-button" disabled={loading || !selectedCandidateId} onClick={onConfirmCandidate}>
					确认并继续
				</button>
			</div>
		</div>
	);
}

function summarizeRuntime(data: RuntimeCheckResponse | null): { ready: number; total: number } {
	const requiredChecks = data?.checks.filter((item) => item.required) ?? [];
	return {
		ready: requiredChecks.filter((item) => item.status === "ok").length,
		total: requiredChecks.length || 6,
	};
}

function checkStatus(data: RuntimeCheckResponse | null, id: string): string {
	const item = data?.checks.find((check) => check.id === id);
	if (!item) {
		return "待检测";
	}
	if (item.status === "ok") {
		return "已配置";
	}
	if (item.status === "warning") {
		return "需确认";
	}
	return "缺失";
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
	} else {
		turns.push({
			id: makeId("history-assistant"),
			role: "assistant",
			content: "这条历史消息是示例或草稿，编辑后可重新发送。",
			createdAt: item.updatedAt,
		});
	}
	return turns;
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
