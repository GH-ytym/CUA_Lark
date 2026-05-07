export type ExecutionStatus =
	| "queued"
	| "parsing"
	| "cli_running"
	| "cli_failed"
	| "cua_running"
	| "completed"
	| "failed"
	| "canceled";

export type TaskStatus = "queued" | "running" | "fallback" | "completed" | "failed" | "canceled";

export type TaskCard = {
	id: string;
	title: string;
	description: string;
	status: TaskStatus;
	owner: "CLI" | "CUA" | "Agent";
	duration: string;
};

export type TimelineStep = {
	id: string;
	label: string;
	detail: string;
	status: "done" | "active" | "pending" | "failed";
};

export type DebugTraceItem = {
	id: string;
	name: string;
	status: ExecutionStatus;
	summary: string;
	payload: string;
	createdAt: string;
};

export type FeishuRuntimeConfig = {
	appName: string;
	apiBaseUrl: string;
	isInFeishuClient: boolean;
	entryUrl: string;
};

export type ResolutionCandidate = {
	name: string;
	entity_type: string;
	entity_id: string;
	score: number;
};

export type ExecutorType = "cli" | "cua" | "none";
export type IntentType =
	| "message_send"
	| "calendar_reschedule"
	| "doc_create"
	| "sheet_update"
	| "multi_task"
	| "unknown";

export type StandardAction = {
	capability_id: string;
	payload: Record<string, unknown>;
	executor_hint: ExecutorType;
	intent_type: IntentType;
};

export type PlannedActionItem = {
	order: number;
	raw_message: string;
	standard_action: StandardAction;
	status: string;
	summary: string;
	needs_confirmation: boolean;
	error_code: number | null;
	execution_payload: Record<string, unknown>;
};

export type ExecutorResult = {
	executor: ExecutorType;
	success: boolean;
	status: ExecutionStatus;
	summary: string;
	payload: Record<string, unknown>;
	error_code: number | null;
	duration_ms: number;
};

export type TaskStepRecord = {
	name: string;
	status: ExecutionStatus;
	summary: string;
	payload: Record<string, unknown>;
	created_at: string;
};

export type ExecutionDetailResponse = {
	task_id: string;
	session_id: string;
	user_id: string;
	raw_message: string;
	status: ExecutionStatus;
	intent_type: IntentType;
	standard_action: StandardAction;
	planned_actions: PlannedActionItem[];
	needs_confirmation: boolean;
	executor_result: ExecutorResult | null;
	steps: TaskStepRecord[];
	created_at: string;
	updated_at: string;
};

export type ExecutionStreamEvent = {
	event: "snapshot" | "step" | "status" | "heartbeat" | "terminal" | "error";
	task_id: string;
	status: ExecutionStatus;
	sequence: number;
	summary: string;
	step: TaskStepRecord | null;
	detail: ExecutionDetailResponse | null;
	emitted_at: string;
};

export type ExecutionActionResponse = {
	task_id: string;
	status: ExecutionStatus;
	summary: string;
	detail: ExecutionDetailResponse;
};

export type RuntimeCheckItem = {
	id: string;
	label: string;
	status: "ok" | "missing" | "warning";
	value: string;
	required: boolean;
	hint: string;
};

export type RuntimeCheckResponse = {
	ready: boolean;
	checks: RuntimeCheckItem[];
	env_template: Record<string, string>;
	install: Record<string, string>;
};

export type RuntimeConfigPayload = {
	dashscope_api_key: string;
	qwen_chat_url: string;
	qwen_model: string;
	lark_cli_path: string;
	lark_cli_workdir: string;
	cua_model_api_key: string;
	cua_model_api_base: string;
	cua_model_name: string;
};

export type RuntimeConfigUpdateResponse = {
	updated_keys: string[];
	detail: RuntimeCheckResponse;
};

export type QwenModelProbePayload = {
	dashscope_api_key: string;
	qwen_chat_url: string;
	qwen_model: string;
};

export type QwenModelProbeResponse = {
	ok: boolean;
	chat_url: string;
	models_url: string;
	models: string[];
	selected_model: string;
	selected_available: boolean;
	message: string;
};

export type LarkCliInstallPayload = {
	package_name: string;
	registry_url: string;
};

export type LarkCliEnablePayload = {
	path: string;
	workdir: string;
};

export type LarkCliActionResponse = {
	ok: boolean;
	message: string;
	package_name?: string;
	install_dir: string;
	bin_path: string;
	command?: string;
	stdout?: string;
	stderr?: string;
	updated_keys: string[];
	detail: RuntimeCheckResponse;
};

export type LarkCliCommandResult = {
	returncode: number;
	stdout: string;
	stderr: string;
};

export type LarkCliAccountCheck = {
	configured: boolean;
	authenticated: boolean;
	account_label: string;
	cli_path: string;
	workdir: string;
	config: LarkCliCommandResult;
	auth_status: LarkCliCommandResult;
	auth_list: LarkCliCommandResult;
	doctor: LarkCliCommandResult | null;
};

export type LarkCliAccountSetupPayload = {
	auth_domain: string;
	use_recommend: boolean;
	force_new_app: boolean;
};

export type LarkCliAccountSetupJob = {
	job_id: string;
	status: "running" | "completed" | "failed" | "canceled";
	step: "check" | "config" | "auth" | "verify" | "done" | "error" | string;
	message: string;
	verification_url: string;
	user_code: string;
	output: string;
	error: string;
	account_label: string;
	started_at: string;
	updated_at: string;
	completed_at: string;
	account: LarkCliAccountCheck | null;
};

export type ExecuteCommandResponse = {
	task_id: string;
	initial_status: ExecutionStatus;
	selected_executor: ExecutorType;
	parsed_intent: IntentType;
	intent_reason: string;
	action_plan: string[];
	parse_source: string;
	standard_action: StandardAction;
	planned_actions: PlannedActionItem[];
	structured_payload: Record<string, unknown>;
	needs_confirmation: boolean;
	confirmation_message: string;
	resolution_candidates: ResolutionCandidate[];
	execution_status: ExecutionStatus;
	execution_summary: string;
	cli_error_code: number | null;
	cua_error_code: number | null;
	cua_should_trigger: boolean;
	execution_payload: Record<string, unknown>;
	accepted_at: string;
};
