import { useEffect, useState } from "react";
import type {
	LarkCliAccountCheck,
	LarkCliAccountSetupJob,
	LarkCliAccountSetupPayload,
	QwenModelProbePayload,
	QwenModelProbeResponse,
	RuntimeCheckResponse,
	RuntimeConfigPayload,
} from "../../types/execution";

type RuntimeCheckPanelProps = {
	data: RuntimeCheckResponse | null;
	loading?: boolean;
	saving?: boolean;
	cliBusy?: boolean;
	accountBusy?: boolean;
	modelBusy?: boolean;
	error?: string;
	message?: string;
	modelProbe: QwenModelProbeResponse | null;
	account: LarkCliAccountCheck | null;
	setupJob: LarkCliAccountSetupJob | null;
	onRefresh: () => void;
	onSave: (payload: RuntimeConfigPayload) => void;
	onProbeModels: (payload: QwenModelProbePayload) => void;
	onRefreshAccount: () => void;
	onStartAccountSetup: (payload: LarkCliAccountSetupPayload) => void;
	onCancelAccountSetup: (jobId: string) => void;
};

const emptyForm: RuntimeConfigPayload = {
	dashscope_api_key: "",
	qwen_chat_url: "",
	qwen_model: "",
	lark_cli_path: "",
	lark_cli_workdir: "",
	cua_model_api_key: "",
	cua_model_api_base: "",
	cua_model_name: "",
};

const defaultAccountForm = {
	auth_domain: "im",
	use_recommend: true,
	force_new_app: false,
};

const runtimeDraftKey = "cua-lark.runtime-config-draft.v1";
const accountDraftKey = "cua-lark.lark-account-draft.v1";

export function RuntimeCheckPanel({
	data,
	loading = false,
	saving = false,
	cliBusy = false,
	accountBusy = false,
	modelBusy = false,
	error = "",
	message = "",
	modelProbe,
	account,
	setupJob,
	onRefresh,
	onSave,
	onProbeModels,
	onRefreshAccount,
	onStartAccountSetup,
	onCancelAccountSetup,
}: RuntimeCheckPanelProps) {
	const [form, setForm] = useState<RuntimeConfigPayload>(() => readStorage(runtimeDraftKey, emptyForm));
	const [accountForm, setAccountForm] = useState(() => readStorage(accountDraftKey, defaultAccountForm));

	useEffect(() => {
		if (!data) {
			return;
		}
		setForm((current) => ({
			...current,
			qwen_chat_url: current.qwen_chat_url || valueFor(data, "qwen_chat_url") || data.env_template.QWEN_CHAT_URL || "",
			qwen_model: current.qwen_model || valueFor(data, "qwen_model") || data.env_template.QWEN_MODEL || "",
			lark_cli_path: current.lark_cli_path || valueFor(data, "lark_cli") || data.env_template.LARK_CLI_PATH || "lark-cli",
			lark_cli_workdir:
				current.lark_cli_workdir || valueFor(data, "lark_cli_workdir") || data.env_template.LARK_CLI_WORKDIR || "./runtime/lark-cli",
			cua_model_api_base: current.cua_model_api_base || valueFor(data, "cua_model_api_base") || data.env_template.CUA_MODEL_API_BASE || "",
			cua_model_name: current.cua_model_name || valueFor(data, "cua_model_name") || data.env_template.CUA_MODEL_NAME || "doubao-vision-pro-32k",
		}));
	}, [data]);

	useEffect(() => {
		writeStorage(runtimeDraftKey, form);
	}, [form]);

	useEffect(() => {
		writeStorage(accountDraftKey, accountForm);
	}, [accountForm]);

	useEffect(() => {
		if (!modelProbe?.selected_model) {
			return;
		}
		setForm((current) => {
			const currentModel = current.qwen_model.trim();
			const shouldUseDetectedModel =
				!currentModel || (modelProbe.models.length > 0 && !modelProbe.models.includes(currentModel));
			return shouldUseDetectedModel ? { ...current, qwen_model: modelProbe.selected_model } : current;
		});
	}, [modelProbe]);

	function updateField(key: keyof RuntimeConfigPayload, value: string) {
		setForm((current) => ({ ...current, [key]: value }));
	}

	function probeModels() {
		onProbeModels({
			dashscope_api_key: form.dashscope_api_key,
			qwen_chat_url: form.qwen_chat_url,
			qwen_model: form.qwen_model,
		});
	}

	function saveDemoConfig() {
		onSave(form);
	}

	return (
		<section className="runtime-check-panel demo-runtime-panel" aria-labelledby="runtime-check-title">
			<header className="demo-runtime-header">
				<div>
					<p className="eyebrow">Runtime</p>
					<h2 id="runtime-check-title">演示配置</h2>
				</div>
				<span className={`settings-score ${data?.ready ? "settings-score--ready" : ""}`}>
					{data?.ready ? "Ready" : "Setup"}
				</span>
			</header>

			{error ? <p className="error-banner">{error}</p> : null}
			{message ? <p className="success-banner">{message}</p> : null}

			<form className="runtime-config-form demo-runtime-card" onSubmit={(event) => event.preventDefault()}>
				<div className="demo-card-title">
					<h3>Qwen</h3>
					<span>{checkStatus(data, "dashscope_api_key")}</span>
				</div>
				<RuntimeInput
					label="Qwen Key"
					type="password"
					value={form.dashscope_api_key}
					placeholder={maskedValue(data, "dashscope_api_key")}
					hint="留空保存时不会覆盖已有 Key。"
					onChange={(value) => updateField("dashscope_api_key", value)}
				/>
				<RuntimeInput
					label="模型"
					value={form.qwen_model}
					placeholder={modelProbe?.selected_model || "qwen-plus"}
					hint="固定使用 DashScope Qwen，可手动输入或检测后选择。"
					onChange={(value) => updateField("qwen_model", value)}
				/>
				<div className="model-probe-panel">
					<div className="model-probe-actions">
						<div>
							<span>模型可用性</span>
							<small>检测当前 Key 可访问的 Qwen 模型。</small>
						</div>
						<button
							type="button"
							className="secondary-button"
							disabled={saving || loading || modelBusy}
							onClick={probeModels}
						>
							{modelBusy ? "检测中..." : "检测并获取模型"}
						</button>
					</div>
					{modelProbe ? (
						<>
							<select
								value={modelProbe.models.includes(form.qwen_model) ? form.qwen_model : ""}
								onChange={(event) => {
									if (event.target.value) {
										updateField("qwen_model", event.target.value);
									}
								}}
								disabled={modelBusy || modelProbe.models.length === 0}
							>
								<option value="">选择检测到的模型</option>
								{modelProbe.models.map((model) => (
									<option value={model} key={model}>
										{model}
									</option>
								))}
							</select>
							<small>
								{modelProbe.selected_available
									? `当前模型 ${modelProbe.selected_model} 可用`
									: `当前模型不在列表中，可继续手动保存自定义名称`}
							</small>
						</>
					) : null}
				</div>
				<div className="runtime-form-actions">
					<button type="button" className="primary-button" disabled={saving || loading} onClick={saveDemoConfig}>
						{saving ? "保存中..." : "保存 Qwen 配置"}
					</button>
				</div>
			</form>

			<form className="runtime-config-form demo-runtime-card" onSubmit={(event) => event.preventDefault()}>
				<div className="demo-card-title">
					<h3>豆包视觉</h3>
					<span>{checkStatus(data, "cua_model_api_key")}</span>
				</div>
				<RuntimeInput
					label="豆包视觉 Key"
					type="password"
					value={form.cua_model_api_key}
					placeholder={maskedValue(data, "cua_model_api_key")}
					hint="仅 CUA 视觉兜底需要；留空不覆盖已有 Key。"
					onChange={(value) => updateField("cua_model_api_key", value)}
				/>
				<RuntimeInput
					label="视觉模型"
					value={form.cua_model_name}
					placeholder="doubao-vision-pro-32k"
					hint="演示固定豆包视觉，可按实际 endpoint/model id 调整。"
					onChange={(value) => updateField("cua_model_name", value)}
				/>
				<div className="runtime-form-actions">
					<button type="button" className="primary-button" disabled={saving || loading} onClick={saveDemoConfig}>
						{saving ? "保存中..." : "保存视觉配置"}
					</button>
				</div>
			</form>

			<div className="lark-account-tool demo-runtime-card">
				<div className="demo-card-title">
					<div>
						<h3>飞书连接</h3>
						<p>{account?.authenticated ? `当前账号：${account.account_label || "已连接"}` : "未连接飞书账号"}</p>
					</div>
					<span>{account?.authenticated ? "已连接" : accountBusy ? "检测中" : "未连接"}</span>
				</div>

				<div className="account-status-grid">
					<div>
						<dt>应用配置</dt>
						<dd>{account?.configured ? "已配置" : "未配置"}</dd>
					</div>
					<div>
						<dt>帐号授权</dt>
						<dd>{account?.authenticated ? "已授权" : "未授权"}</dd>
					</div>
					<div>
						<dt>当前帐号</dt>
						<dd>{account?.account_label || setupJob?.account_label || "-"}</dd>
					</div>
				</div>

				{setupJob ? (
					<div className={`setup-job setup-job--${setupJob.status}`}>
						<header>
							<strong>{setupJob.message}</strong>
							<span>{setupJob.status}</span>
						</header>
						{setupJob.verification_url ? (
							<a href={setupJob.verification_url} target="_blank" rel="noreferrer">
								打开飞书授权链接
							</a>
						) : null}
						{setupJob.user_code ? <code>验证码：{setupJob.user_code}</code> : null}
						{setupJob.error ? <p>{setupJob.error}</p> : null}
						{setupJob.output ? <pre>{setupJob.output}</pre> : null}
					</div>
				) : null}

				<div className="runtime-form-actions">
					<button type="button" className="secondary-button" disabled={accountBusy} onClick={onRefreshAccount}>
						重新检测帐号
					</button>
					{setupJob?.status === "running" ? (
						<button
							type="button"
							className="secondary-button"
							disabled={accountBusy}
							onClick={() => onCancelAccountSetup(setupJob.job_id)}
						>
							取消配置
						</button>
					) : null}
					<button
						type="button"
						className="primary-button"
						disabled={accountBusy || setupJob?.status === "running"}
						onClick={() => onStartAccountSetup(accountForm)}
					>
						{accountBusy ? "处理中..." : account?.authenticated ? "重新连接飞书" : "连接飞书"}
					</button>
				</div>
			</div>
		</section>
	);
}

function RuntimeInput({
	label,
	value,
	placeholder,
	hint,
	type = "text",
	onChange,
}: {
	label: string;
	value: string;
	placeholder: string;
	hint: string;
	type?: "text" | "password";
	onChange: (value: string) => void;
}) {
	const id = `runtime-${label.toLowerCase().replaceAll("_", "-")}`;
	return (
		<label className="runtime-input" htmlFor={id}>
			<span>{label}</span>
			<input id={id} type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
			<small>{hint}</small>
		</label>
	);
}

function valueFor(data: RuntimeCheckResponse, id: string): string {
	const item = data.checks.find((check) => check.id === id);
	if (!item || item.value === "未配置" || item.value === "已配置") {
		return "";
	}
	return item.value;
}

function maskedValue(data: RuntimeCheckResponse | null, id: string): string {
	const item = data?.checks.find((check) => check.id === id);
	return item?.value === "已配置" ? "已配置，留空不修改" : "未配置";
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

function readStorage<T extends Record<string, unknown>>(key: string, fallback: T): T {
	if (typeof window === "undefined") {
		return fallback;
	}
	try {
		const raw = window.localStorage.getItem(key);
		if (!raw) {
			return fallback;
		}
		const parsed = JSON.parse(raw) as Partial<T>;
		if (!parsed || typeof parsed !== "object") {
			return fallback;
		}
		return { ...fallback, ...parsed };
	} catch {
		return fallback;
	}
}

function writeStorage(key: string, value: Record<string, unknown>) {
	if (typeof window === "undefined") {
		return;
	}
	try {
		window.localStorage.setItem(key, JSON.stringify(value));
	} catch {
		// Local storage can be unavailable in restricted containers.
	}
}
