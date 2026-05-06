import type {
	ExecuteCommandResponse,
	ExecutionDetailResponse,
	ExecutionStatus,
	ExecutionStreamEvent,
	DebugTraceItem,
	TaskCard,
	TaskStepRecord,
	TaskStatus,
	TimelineStep,
} from "../types/execution";

export type ExecutionViewState = {
	taskId: string;
	response: ExecuteCommandResponse;
	detail: ExecutionDetailResponse | null;
	lastEvent: ExecutionStreamEvent | null;
	streamConnected: boolean;
	streamError: string;
};

const terminalStatuses: ExecutionStatus[] = ["completed", "failed", "canceled"];

export function isTerminalExecutionStatus(status: ExecutionStatus): boolean {
	return terminalStatuses.includes(status);
}

export function mapExecutionStatusToTaskStatus(status: ExecutionStatus, needsConfirmation = false): TaskStatus {
	if (status === "cua_running") {
		return "fallback";
	}
	if (status === "completed") {
		return "completed";
	}
	if (status === "failed" || status === "cli_failed") {
		return "failed";
	}
	if (status === "canceled") {
		return "canceled";
	}
	return status === "queued" ? "queued" : "running";
}

export function buildTaskCards(viewState: ExecutionViewState | null): TaskCard[] {
	if (!viewState) {
		return [];
	}
	const { response, detail } = viewState;
	const status = detail?.status ?? response.execution_status ?? response.initial_status;
	const result = detail?.executor_result;
	const owner =
		result?.executor === "cli" || response.selected_executor === "cli"
			? "CLI"
			: result?.executor === "cua" || response.selected_executor === "cua"
				? "CUA"
				: "Agent";
	const description = result?.summary || response.execution_summary || response.intent_reason || "任务已受理。";

	return [
		{
			id: response.task_id,
			title: titleForStatus(status),
			description,
			status: mapExecutionStatusToTaskStatus(status),
			owner,
			duration: formatDuration(result?.duration_ms),
		},
	];
}

export function buildTimelineSteps(viewState: ExecutionViewState | null): TimelineStep[] {
	if (!viewState) {
		return [
			{
				id: "receive",
				label: "接收",
				detail: "等待提交指令。",
				status: "active",
			},
			{
				id: "parse",
				label: "解析",
				detail: "待识别意图和能力。",
				status: "pending",
			},
			{
				id: "cli",
				label: "CLI",
				detail: "优先使用确定性执行链路。",
				status: "pending",
			},
			{
				id: "cua",
				label: "CUA",
				detail: "CLI 失败后先由模型诊断，再按结论接管。",
				status: "pending",
			},
			{
				id: "result",
				label: "结果",
				detail: "等待执行结果。",
				status: "pending",
			},
		];
	}
	const { response, detail } = viewState;
	const steps = detail?.steps ?? [];
	const currentStatus = detail?.status ?? response.execution_status;
	const hasIntent = hasStepNamed(steps, "intent_parsed");
	const hasCliStarted = hasStepMatching(steps, /(^|_)cli_started$/);
	const hasCliFinished = hasStepMatching(steps, /(^|_)cli_finished$/);
	const hasCliDiagnosed = hasStepMatching(steps, /(^|_)cli_diagnosed$/);
	const hasCuaStarted = hasStepMatching(steps, /(^|_)cua_started$/);
	const hasCuaFinished = hasStepMatching(steps, /(^|_)cua_finished$/);
	const terminal = isTerminalExecutionStatus(currentStatus);

	return [
		{
			id: "receive",
			label: "接收",
			detail: response.task_id ? `任务 ${shortId(response.task_id)} 已创建。` : "任务已受理。",
			status: "done",
		},
		{
			id: "parse",
			label: "解析",
			detail: hasIntent ? response.intent_reason || "意图和能力已解析。" : "正在识别意图和能力。",
			status: currentStatus === "parsing" && !hasIntent ? "active" : hasIntent ? "done" : "pending",
		},
		{
			id: "cli",
			label: "CLI",
			detail: cliTimelineDetail(currentStatus, hasCliStarted, hasCliFinished, hasCliDiagnosed),
			status: cliTimelineStatus(currentStatus, hasCliStarted, hasCliFinished),
		},
		{
			id: "cua",
			label: "CUA",
			detail: cuaTimelineDetail(currentStatus, hasCuaStarted, hasCuaFinished, response.cua_should_trigger),
			status: cuaTimelineStatus(currentStatus, hasCuaStarted, hasCuaFinished),
		},
		{
			id: "result",
			label: "结果",
			detail: terminal ? statusLabel(currentStatus) : "执行中，等待最终结果。",
			status: resultTimelineStatus(currentStatus),
		},
	];
}

export function buildDetailItems(viewState: ExecutionViewState | null): [string, string][] {
	if (!viewState) {
		return [
			["当前状态", "尚未提交任务"],
			["联调目标", "提交任务、订阅状态流、展示详情"],
			["前端职责", "对齐 A 线 API 与 B 线 CUA 状态"],
		];
	}
	const { response, detail, lastEvent, streamConnected, streamError } = viewState;
	const result = detail?.executor_result;
	return [
		["任务 ID", response.task_id],
		["会话", `${detail?.session_id ?? "-"} / ${detail?.user_id ?? "-"}`],
		["状态", statusLabel(detail?.status ?? response.execution_status)],
		["意图", detail?.intent_type ?? response.parsed_intent],
		["能力", detail?.standard_action.capability_id ?? response.standard_action.capability_id],
		["子任务数", String(detail?.planned_actions.length ?? response.planned_actions.length)],
		["执行摘要", result?.summary || response.execution_summary || "-"],
		["CLI 错误码", stringifyNullable(result?.executor === "cli" ? result.error_code : response.cli_error_code)],
		["CUA 错误码", stringifyNullable(result?.executor === "cua" ? result.error_code : response.cua_error_code)],
		["CUA 接管", response.cua_should_trigger ? "是" : "否"],
		["流状态", streamError || (streamConnected ? "已连接" : isTerminalExecutionStatus(detail?.status ?? response.execution_status) ? "已结束" : "未连接")],
		["最新事件", lastEvent ? `${lastEvent.event} #${lastEvent.sequence}` : "-"],
	];
}

export function buildDebugTrace(viewState: ExecutionViewState | null): DebugTraceItem[] {
	const steps = viewState?.detail?.steps ?? [];
	return steps.map((step, index) => ({
		id: `${index}-${step.name}-${step.created_at}`,
		name: labelForStep(step.name),
		status: step.status,
		summary: step.summary || statusLabel(step.status),
		payload: stringifyPayload(step.payload),
		createdAt: formatTime(step.created_at),
	}));
}

export function buildIssueSummary(viewState: ExecutionViewState | null): {
	title: string;
	description: string;
	actionHint: string;
	severity: "info" | "warning" | "danger";
} | null {
	if (!viewState) {
		return null;
	}
	const { response, detail, streamError } = viewState;
	const status = detail?.status ?? response.execution_status;
	const errorCode = detail?.executor_result?.error_code ?? response.cua_error_code ?? response.cli_error_code;
	if (streamError) {
		return {
			title: "状态流连接异常",
			description: streamError,
			actionHint: "可以点击手动刷新，前端会用详情接口兜底同步。",
			severity: "warning",
		};
	}
	if (status === "failed" || status === "cli_failed") {
		return {
			title: status === "cli_failed" ? "CLI 执行失败" : "任务执行失败",
			description: response.execution_summary || detail?.executor_result?.summary || "后端返回失败状态。",
			actionHint: actionHintForError(errorCode),
			severity: "danger",
		};
	}
	if (status === "canceled") {
		return {
			title: "任务已取消",
			description: "当前任务已从前端控制面板取消。",
			actionHint: "需要继续时可直接重试同一条指令。",
			severity: "warning",
		};
	}
	return null;
}

export function mergeStreamEvent(
	currentDetail: ExecutionDetailResponse | null,
	event: ExecutionStreamEvent,
): ExecutionDetailResponse | null {
	if (event.detail) {
		return event.detail;
	}
	if (!currentDetail || !event.step) {
		return currentDetail;
	}
	if (hasStep(currentDetail.steps, event.step)) {
		return currentDetail;
	}
	return {
		...currentDetail,
		status: event.status,
		steps: [...currentDetail.steps, event.step],
		updated_at: event.emitted_at,
	};
}

function hasStep(steps: TaskStepRecord[], nextStep: TaskStepRecord): boolean {
	return steps.some(
		(step) =>
			step.name === nextStep.name &&
			step.status === nextStep.status &&
			step.created_at === nextStep.created_at &&
			step.summary === nextStep.summary,
	);
}

function titleForStatus(status: ExecutionStatus): string {
	if (status === "completed") {
		return "任务已完成";
	}
	if (status === "failed" || status === "cli_failed") {
		return "任务失败";
	}
	if (status === "cua_running") {
		return "CUA 接管中";
	}
	if (status === "canceled") {
		return "任务已取消";
	}
	if (status === "parsing") {
		return "解析中";
	}
	if (status === "cli_running") {
		return "CLI 执行中";
	}
	return "任务已受理";
}

function timelineStatusForStep(step: TaskStepRecord, index: number, steps: TaskStepRecord[]): TimelineStep["status"] {
	if (step.status === "failed" || step.status === "cli_failed") {
		return "failed";
	}
	if (index === steps.length - 1 && !isTerminalExecutionStatus(step.status)) {
		return "active";
	}
	return "done";
}

function hasStepNamed(steps: TaskStepRecord[], name: string): boolean {
	return steps.some((step) => step.name === name);
}

function hasStepMatching(steps: TaskStepRecord[], pattern: RegExp): boolean {
	return steps.some((step) => pattern.test(step.name));
}

function cliTimelineStatus(
	status: ExecutionStatus,
	hasStarted: boolean,
	hasFinished: boolean,
): TimelineStep["status"] {
	if (status === "cli_running") {
		return "active";
	}
	if (status === "cli_failed") {
		return "failed";
	}
	if (hasFinished) {
		return "done";
	}
	if (hasStarted) {
		return "active";
	}
	return "pending";
}

function cliTimelineDetail(
	status: ExecutionStatus,
	hasStarted: boolean,
	hasFinished: boolean,
	hasDiagnosed: boolean,
): string {
	if (hasDiagnosed) {
		return "CLI 已返回错误，模型已完成原因诊断。";
	}
	if (status === "cli_running" || hasStarted) {
		return hasFinished ? "CLI 已返回结果。" : "CLI 正在执行。";
	}
	if (status === "cli_failed") {
		return "CLI 失败，等待模型诊断是否接管。";
	}
	return "未进入 CLI 阶段。";
}

function cuaTimelineStatus(
	status: ExecutionStatus,
	hasStarted: boolean,
	hasFinished: boolean,
): TimelineStep["status"] {
	if (status === "cua_running") {
		return "active";
	}
	if (hasFinished) {
		return status === "failed" ? "failed" : "done";
	}
	if (hasStarted) {
		return "active";
	}
	return "pending";
}

function cuaTimelineDetail(
	status: ExecutionStatus,
	hasStarted: boolean,
	hasFinished: boolean,
	shouldTrigger: boolean,
): string {
	if (status === "cua_running") {
		return "CUA 正在接管桌面操作。";
	}
	if (hasFinished) {
		return status === "failed" ? "CUA 已结束，但任务失败。" : "CUA 已完成接管。";
	}
	if (shouldTrigger || hasStarted) {
		return "模型诊断确认需要接管，等待 CUA 回写。";
	}
	return "尚未触发，或模型诊断后判定无需接管。";
}

function resultTimelineStatus(status: ExecutionStatus): TimelineStep["status"] {
	if (status === "completed") {
		return "done";
	}
	if (status === "failed" || status === "canceled" || status === "cli_failed") {
		return "failed";
	}
	return "active";
}

function shortId(value: string): string {
	return value.length > 8 ? value.slice(0, 8) : value;
}

function labelForStep(name: string): string {
	const labels: Record<string, string> = {
		task_created: "任务受理",
		intent_parsed: "意图解析",
		cli_started: "CLI 开始",
		cli_finished: "CLI 结束",
		cli_diagnosed: "模型诊断",
		structured_diagnosed: "模型诊断",
		cua_started: "CUA 接管",
		cua_finished: "CUA 结束",
	};
	if (labels[name]) {
		return labels[name];
	}
	const actionMatch = name.match(/^action_(\d+)_(.+)$/);
	if (!actionMatch) {
		return name;
	}
	const [, order, suffix] = actionMatch;
	return `子任务 ${order} · ${labels[suffix] ?? suffix.replaceAll("_", " ")}`;
}

function statusLabel(status: ExecutionStatus): string {
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

function formatDuration(durationMs: number | undefined): string {
	if (typeof durationMs !== "number" || Number.isNaN(durationMs) || durationMs <= 0) {
		return "-";
	}
	if (durationMs < 1000) {
		return `${Math.round(durationMs)}ms`;
	}
	return `${(durationMs / 1000).toFixed(1)}s`;
}

function stringifyNullable(value: number | null | undefined): string {
	return value === null || typeof value === "undefined" ? "-" : String(value);
}

function stringifyPayload(payload: Record<string, unknown>): string {
	const keys = Object.keys(payload);
	if (keys.length === 0) {
		return "-";
	}
	try {
		return JSON.stringify(payload);
	} catch {
		return String(payload);
	}
}

function formatTime(value: string): string {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return value;
	}
	return date.toLocaleTimeString("zh-CN", {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}

function actionHintForError(errorCode: number | null | undefined): string {
	const hints: Record<number, string> = {
		1: "疑似限流，可稍后重试。",
		2: "CLI 暂不支持该能力，确认 CUA fallback 是否触发。",
		3: "权限不足，请检查飞书授权、群权限或 Lark CLI 登录状态。",
		4: "输入或返回结果无效，请检查目标对象和消息内容。",
		5: "执行异常，可重试并查看调试轨迹。",
		6: "执行超时，可取消后重试，或缩短任务范围。",
		7: "需要切换执行器，请关注 CUA 接管步骤。",
	};
	if (typeof errorCode === "number" && hints[errorCode]) {
		return hints[errorCode];
	}
	return "可查看调试轨迹定位失败步骤，必要时重试任务。";
}
