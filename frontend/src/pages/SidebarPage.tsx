import { useCallback, useEffect, useMemo, useState } from "react";
import { CommandComposer } from "../components/chat/CommandComposer";
import { ExecutionFeed } from "../components/chat/ExecutionFeed";
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
	buildDetailItems,
	buildDebugTrace,
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
const MOCK_INJECTED_MESSAGE = "给梅家济发消息：“hello”";

export function SidebarPage() {
	const feishuConfig = getFeishuRuntimeConfig();
	const [message, setMessage] = useState(MOCK_INJECTED_MESSAGE);
	const [loading, setLoading] = useState(false);
	const [response, setResponse] = useState<ExecuteCommandResponse | null>(null);
	const [detail, setDetail] = useState<ExecutionDetailResponse | null>(null);
	const [lastEvent, setLastEvent] = useState<ExecutionStreamEvent | null>(null);
	const [error, setError] = useState("");
	const [selectedCandidateId, setSelectedCandidateId] = useState("");
	const [traceQuery, setTraceQuery] = useState("");
	const [demoMode, setDemoMode] = useState(false);
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

	async function submitCommand(confirmedEntityId = "", messageOverride = "") {
		const nextMessage = (messageOverride || message).trim();
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
			setDetail(null);
			setLastEvent(null);
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

	return (
		<main className={`sidebar-page ${demoMode ? "sidebar-page--demo" : ""}`}>
			<section className="hero-card" aria-labelledby="hero-title">
				<div>
					<p className="eyebrow">C 线联调面板</p>
					<h2 id="hero-title">{demoMode ? "演示模式：执行状态高亮" : "前端已接入 A/B 执行链路"}</h2>
					<p>
						提交指令后接收后端任务受理结果，订阅执行状态流，并展示 CLI 执行、CUA 接管、完成或失败详情。
					</p>
				</div>
				<div className="hero-metrics" aria-label="首日验收项">
					<span>{response ? currentStatus : "Ready"}</span>
					<span>{traceItems.length} steps</span>
					<span>{demoMode ? "Demo On" : "Demo Off"}</span>
				</div>
			</section>

			<section className="feishu-setup-card" aria-labelledby="feishu-setup-title">
				<div>
					<p className="section-kicker">Feishu AppLink</p>
					<h2 id="feishu-setup-title">可作为飞书网页应用入口</h2>
					<p>
						把部署后的 HTTPS 地址填入飞书开放平台的网页应用或侧边栏入口，当前页面会自动读取后端 API 地址并适配飞书客户端容器。
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

			<section className="panel control-panel" aria-labelledby="control-title">
				<div className="panel-title-row">
					<div>
						<p className="section-kicker">06 · 控制台</p>
						<h2 id="control-title">刷新 / 重试 / 取消 / 演示</h2>
					</div>
					<span className="wire-tag">Console</span>
				</div>
				<div className="control-actions">
					<button type="button" className="secondary-button" disabled={loading || !response} onClick={() => void refreshDetail()}>
						手动刷新
					</button>
					<button type="button" className="secondary-button" disabled={loading || !canCancel} onClick={() => void cancelCurrentTask()}>
						取消任务
					</button>
					<button type="button" className="primary-button" disabled={loading || !response} onClick={() => void retryCurrentCommand()}>
						重试当前指令
					</button>
					<label className="toggle-control">
						<input type="checkbox" checked={demoMode} onChange={(event) => setDemoMode(event.target.checked)} />
						<span>演示模式</span>
					</label>
				</div>
			</section>

			<div className="layout-grid">
				<CommandComposer value={message} disabled={loading} onChange={setMessage} onSubmit={() => void submitCommand()} />
				<ExecutionFeed tasks={tasks} />
				<StatusTimeline steps={timelineSteps} />
				<ResultDetail title={response?.needs_confirmation ? "待确认详情" : "执行详情"} items={detailItems} />
			</div>

			{issueSummary ? (
				<ErrorState
					title={issueSummary.title}
					description={issueSummary.description}
					actionHint={issueSummary.actionHint}
					severity={issueSummary.severity}
					onRefresh={() => void refreshDetail()}
					onRetry={() => void retryCurrentCommand()}
					onCancel={() => void cancelCurrentTask()}
					canCancel={canCancel}
					disabled={loading}
				/>
			) : null}

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
						{candidates.length > 0 ? (
							<>
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
							<div className="confirmation-empty">
								<strong>没有可确认的候选对象</strong>
								<p>
									当前本地通讯录没有匹配结果，或飞书 CLI 缺少 `contact:user:search` 权限。请先补授权并同步通讯录，或直接输入明确的 open_id / chat_id。
								</p>
								<code>runtime/lark-cli/node_modules/.bin/lark-cli auth login --scope "contact:user:search"</code>
							</div>
						)}
					</>
				) : (
					<p className="empty-state">当对象解析进入灰区时，这里会展示候选人或群聊供你确认。</p>
				)}
			</section>

			<DebugTracePanel items={traceItems} query={traceQuery} onQueryChange={setTraceQuery} />
		</main>
	);
}
