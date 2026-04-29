export type TaskStatus = "queued" | "running" | "fallback" | "completed" | "failed";

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
	status: "done" | "active" | "pending";
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

export type ExecuteCommandResponse = {
	task_id: string;
	initial_status: string;
	selected_executor: "cli" | "cua" | "none";
	parsed_intent: string;
	intent_reason: string;
	action_plan: string[];
	parse_source: string;
	structured_payload: Record<string, unknown>;
	needs_confirmation: boolean;
	confirmation_message: string;
	resolution_candidates: ResolutionCandidate[];
	accepted_at: string;
};
