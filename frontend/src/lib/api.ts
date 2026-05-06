import type {
	ExecuteCommandResponse,
	ExecutionActionResponse,
	ExecutionDetailResponse,
	FeishuRuntimeConfig,
	LarkCliActionResponse,
	LarkCliAccountCheck,
	LarkCliAccountSetupJob,
	LarkCliAccountSetupPayload,
	LarkCliEnablePayload,
	LarkCliInstallPayload,
	QwenModelProbePayload,
	QwenModelProbeResponse,
	RuntimeConfigPayload,
	RuntimeConfigUpdateResponse,
	RuntimeCheckResponse,
} from "../types/execution";

const getEnv = (key: string, fallback = "") => {
	const value = import.meta.env[key] as string | undefined;
	return value && value.length > 0 ? value : fallback;
};

export function getFeishuRuntimeConfig(): FeishuRuntimeConfig {
	const apiBaseUrl = getEnv("VITE_API_BASE_URL", "http://127.0.0.1:8000");
	const configuredEntry = getEnv("VITE_FEISHU_APP_ENTRY_URL", window.location.origin);
	const userAgent = window.navigator.userAgent.toLowerCase();

	return {
		appName: getEnv("VITE_APP_NAME", "CUA-Lark"),
		apiBaseUrl,
		entryUrl: configuredEntry,
		isInFeishuClient: userAgent.includes("lark") || userAgent.includes("feishu"),
	};
}

type ExecuteCommandPayload = {
	message: string;
	session_id: string;
	user_id: string;
	conversation_type?: string;
	context_hint?: string;
	confirmed_entity_id?: string;
};

export async function executeAgentCommand(
	payload: ExecuteCommandPayload,
): Promise<ExecuteCommandResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/agent/execute`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			conversation_type: "chat",
			context_hint: "",
			...payload,
		}),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(errorText || `Request failed with status ${response.status}`);
	}
	return (await response.json()) as ExecuteCommandResponse;
}

export async function getExecutionDetail(taskId: string): Promise<ExecutionDetailResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/executions/${encodeURIComponent(taskId)}`);
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(errorText || `Request failed with status ${response.status}`);
	}
	return (await response.json()) as ExecutionDetailResponse;
}

export async function cancelExecution(taskId: string): Promise<ExecutionActionResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/executions/${encodeURIComponent(taskId)}/cancel`, {
		method: "POST",
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(errorText || `Request failed with status ${response.status}`);
	}
	return (await response.json()) as ExecutionActionResponse;
}

export function getExecutionStreamUrl(taskId: string): string {
	const config = getFeishuRuntimeConfig();
	return `${config.apiBaseUrl}/api/executions/${encodeURIComponent(taskId)}/stream`;
}

export async function getRuntimeCheck(): Promise<RuntimeCheckResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/runtime-check`);
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(errorText || `Request failed with status ${response.status}`);
	}
	return (await response.json()) as RuntimeCheckResponse;
}

export async function updateRuntimeConfig(payload: RuntimeConfigPayload): Promise<RuntimeConfigUpdateResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/runtime-config`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(errorText || `Request failed with status ${response.status}`);
	}
	return (await response.json()) as RuntimeConfigUpdateResponse;
}

export async function probeQwenModels(payload: QwenModelProbePayload): Promise<QwenModelProbeResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/qwen/models`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as QwenModelProbeResponse;
}

export async function installLarkCli(payload: LarkCliInstallPayload): Promise<LarkCliActionResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/install`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliActionResponse;
}

export async function enableLarkCli(payload: LarkCliEnablePayload): Promise<LarkCliActionResponse> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/enable`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliActionResponse;
}

export async function getLarkCliAccount(): Promise<LarkCliAccountCheck> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/account`);
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliAccountCheck;
}

export async function startLarkCliAccountSetup(payload: LarkCliAccountSetupPayload): Promise<LarkCliAccountSetupJob> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/account/setup`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliAccountSetupJob;
}

export async function getLarkCliAccountSetup(jobId: string): Promise<LarkCliAccountSetupJob> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/account/setup/${encodeURIComponent(jobId)}`);
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliAccountSetupJob;
}

export async function cancelLarkCliAccountSetup(jobId: string): Promise<LarkCliAccountSetupJob> {
	const config = getFeishuRuntimeConfig();
	const response = await fetch(`${config.apiBaseUrl}/api/debug/lark-cli/account/setup/${encodeURIComponent(jobId)}/cancel`, {
		method: "POST",
	});
	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(extractErrorMessage(errorText, `Request failed with status ${response.status}`));
	}
	return (await response.json()) as LarkCliAccountSetupJob;
}

function extractErrorMessage(errorText: string, fallback: string): string {
	if (!errorText) {
		return fallback;
	}
	try {
		const parsed = JSON.parse(errorText) as { detail?: unknown };
		if (typeof parsed.detail === "string") {
			return parsed.detail;
		}
	} catch {
		return errorText;
	}
	return errorText;
}
