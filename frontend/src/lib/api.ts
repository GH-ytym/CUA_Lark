import type { ExecuteCommandResponse, FeishuRuntimeConfig } from "../types/execution";

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
