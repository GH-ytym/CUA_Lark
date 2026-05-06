const apiBaseUrl = process.env.VITE_API_BASE_URL || process.env.API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
	const response = await fetch(`${apiBaseUrl}${path}`, options);
	const body = await response.text();
	if (!response.ok) {
		throw new Error(`${options.method || "GET"} ${path} failed: ${response.status} ${body}`);
	}
	return body ? JSON.parse(body) : {};
}

async function main() {
	const health = await request("/api/health");
	if (health.status !== "ok") {
		throw new Error(`unexpected health payload: ${JSON.stringify(health)}`);
	}

	const executePayload = await request("/api/agent/execute", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			message: "给项目群发今晚发布",
			session_id: "frontend-smoke-session",
			user_id: "frontend-smoke-user",
			conversation_type: "chat",
			context_hint: "",
		}),
	});

	if (!executePayload.task_id) {
		throw new Error(`missing task_id: ${JSON.stringify(executePayload)}`);
	}

	const detail = await request(`/api/executions/${encodeURIComponent(executePayload.task_id)}`);
	if (detail.task_id !== executePayload.task_id || !Array.isArray(detail.steps)) {
		throw new Error(`invalid execution detail: ${JSON.stringify(detail)}`);
	}

	const streamResponse = await fetch(`${apiBaseUrl}/api/executions/${encodeURIComponent(executePayload.task_id)}/stream`);
	const streamText = await streamResponse.text();
	if (!streamResponse.ok || !streamText.includes("event: snapshot") || !streamText.includes("event: terminal")) {
		throw new Error(`invalid stream output: ${streamText.slice(0, 300)}`);
	}

	console.log(
		JSON.stringify(
			{
				ok: true,
				apiBaseUrl,
				taskId: executePayload.task_id,
				status: detail.status,
				steps: detail.steps.length,
			},
			null,
			2,
		),
	);
}

main().catch((error) => {
	console.error(error instanceof Error ? error.message : error);
	process.exit(1);
});
