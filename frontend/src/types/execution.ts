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
