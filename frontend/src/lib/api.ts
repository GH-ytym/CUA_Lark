import type { FeishuRuntimeConfig } from "../types/execution";

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
