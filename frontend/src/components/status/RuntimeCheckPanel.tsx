import { useEffect, useState } from "react";
import type {
	LarkCliAccountCheck,
	LarkCliAccountSetupJob,
	LarkCliAccountSetupPayload,
	LarkCliEnablePayload,
	LarkCliInstallPayload,
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
	onInstallCli: (payload: LarkCliInstallPayload) => void;
	onEnableCli: (payload: LarkCliEnablePayload) => void;
	onRefreshAccount: () => void;
	onStartAccountSetup: (payload: LarkCliAccountSetupPayload) => void;
	onCancelAccountSetup: (jobId: string) => void;
};

const statusLabel = {
	ok: "已就绪",
	missing: "缺失",
	warning: "注意",
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

const defaultCliForm = {
	package_name: "@larksuite/cli",
	registry_url: "",
	path: "",
	workdir: "./runtime/lark-cli",
};

const defaultAccountForm = {
	auth_domain: "im",
	use_recommend: false,
	force_new_app: false,
};

const runtimeDraftKey = "cua-lark.runtime-config-draft.v1";
const cliDraftKey = "cua-lark.lark-cli-draft.v1";
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
	onInstallCli,
	onEnableCli,
	onRefreshAccount,
	onStartAccountSetup,
	onCancelAccountSetup,
}: RuntimeCheckPanelProps) {
	const [form, setForm] = useState<RuntimeConfigPayload>(() => readStorage(runtimeDraftKey, emptyForm));
	const [cliForm, setCliForm] = useState(() => readStorage(cliDraftKey, defaultCliForm));
	const [accountForm, setAccountForm] = useState(() => readStorage(accountDraftKey, defaultAccountForm));
	const envEntries = Object.entries(data?.env_template ?? {});
	const installEntries = Object.entries(data?.install ?? {});

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
			cua_model_api_base: current.cua_model_api_base || valueFor(data, "cua_model_api_base"),
			cua_model_name: current.cua_model_name || valueFor(data, "cua_model_name"),
		}));
		setCliForm((current) => ({
			...current,
			path: valueFor(data, "lark_cli") || current.path || data.env_template.LARK_CLI_PATH || "lark-cli",
			workdir: valueFor(data, "lark_cli_workdir") || current.workdir || data.env_template.LARK_CLI_WORKDIR || "./runtime/lark-cli",
		}));
	}, [data]);

	useEffect(() => {
		writeStorage(runtimeDraftKey, form);
	}, [form]);

	useEffect(() => {
		writeStorage(cliDraftKey, cliForm);
	}, [cliForm]);

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

	function updateCliField(key: keyof typeof defaultCliForm, value: string) {
		setCliForm((current) => ({ ...current, [key]: value }));
	}

	function updateAccountField(key: keyof typeof defaultAccountForm, value: string | boolean) {
		setAccountForm((current) => ({ ...current, [key]: value }));
	}

	function probeModels() {
		onProbeModels({
			dashscope_api_key: form.dashscope_api_key,
			qwen_chat_url: form.qwen_chat_url,
			qwen_model: form.qwen_model,
		});
	}

	return (
		<section className="panel runtime-check-panel" aria-labelledby="runtime-check-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">00 · 运行准备</p>
					<h2 id="runtime-check-title">环境检测与配置清单</h2>
				</div>
				<span className={`wire-tag runtime-ready-${data?.ready ? "ok" : "missing"}`}>
					{data?.ready ? "Ready" : "Setup"}
				</span>
			</div>

			<div className="runtime-check-actions">
				<p>{data?.ready ? "必需项已配置，可以执行真实链路。" : "请先补齐缺失的必需项，再跑真实飞书链路。"}</p>
				<button type="button" className="secondary-button" onClick={onRefresh} disabled={loading || saving}>
					{loading ? "检测中..." : "重新检测"}
				</button>
			</div>

			{error ? <p className="error-banner">{error}</p> : null}
			{message ? <p className="success-banner">{message}</p> : null}

			<form
				className="runtime-config-form"
				onSubmit={(event) => {
					event.preventDefault();
					onSave(form);
				}}
			>
				<RuntimeInput
					label="DASHSCOPE_API_KEY"
					type="password"
					value={form.dashscope_api_key}
					placeholder={maskedValue(data, "dashscope_api_key")}
					hint="阿里云百炼 API Key。留空表示不修改已有值。"
					onChange={(value) => updateField("dashscope_api_key", value)}
				/>
				<RuntimeInput
					label="QWEN_CHAT_URL"
					value={form.qwen_chat_url}
					placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
					hint="Qwen OpenAI-compatible chat completions 地址。"
					onChange={(value) => updateField("qwen_chat_url", value)}
				/>
				<RuntimeInput
					label="QWEN_MODEL"
					value={form.qwen_model}
					placeholder={modelProbe?.selected_model || "qwen-plus"}
					hint="意图解析模型名；可从检测结果选择，也可手动填写自定义模型。"
					onChange={(value) => updateField("qwen_model", value)}
				/>
				<div className="model-probe-panel">
					<div className="model-probe-actions">
						<div>
							<span>可用模型检测</span>
							<small>根据当前 URL/API Key 自动读取 `/models`，不会回显密钥。</small>
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
							<code>{modelProbe.models_url}</code>
							<small>
								{modelProbe.selected_available
									? `当前模型 ${modelProbe.selected_model} 可用`
									: `当前模型不在列表中，可继续手动保存自定义名称`}
							</small>
						</>
					) : null}
				</div>
				<RuntimeInput
					label="LARK_CLI_PATH"
					value={form.lark_cli_path}
					placeholder="lark-cli 或绝对路径"
					hint="lark-cli 可执行文件路径；在 PATH 中可填 lark-cli。"
					onChange={(value) => updateField("lark_cli_path", value)}
				/>
				<RuntimeInput
					label="LARK_CLI_WORKDIR"
					value={form.lark_cli_workdir}
					placeholder="./runtime/lark-cli"
					hint="CLI 执行工作目录；本地下载默认写入这里。"
					onChange={(value) => updateField("lark_cli_workdir", value)}
				/>
				<RuntimeInput
					label="CUA_MODEL_API_KEY"
					type="password"
					value={form.cua_model_api_key}
					placeholder={maskedValue(data, "cua_model_api_key")}
					hint="启用视觉兜底时填写。留空表示不修改已有值。"
					onChange={(value) => updateField("cua_model_api_key", value)}
				/>
				<RuntimeInput
					label="CUA_MODEL_API_BASE"
					value={form.cua_model_api_base}
					placeholder="视觉模型 OpenAI-compatible base URL"
					hint="启用视觉兜底时填写。"
					onChange={(value) => updateField("cua_model_api_base", value)}
				/>
				<RuntimeInput
					label="CUA_MODEL_NAME"
					value={form.cua_model_name}
					placeholder="视觉模型名 / endpoint id"
					hint="启用视觉兜底时填写。"
					onChange={(value) => updateField("cua_model_name", value)}
				/>
				<div className="runtime-form-actions">
					<button
						type="button"
						className="secondary-button"
						disabled={saving || loading}
						onClick={() => {
							clearStorage(runtimeDraftKey);
							setForm(emptyForm);
						}}
					>
						清空本地草稿
					</button>
					<button type="submit" className="primary-button" disabled={saving || loading}>
						{saving ? "保存中..." : "保存到 .env 并检测"}
					</button>
				</div>
			</form>

			<div className="lark-cli-tool">
				<div className="lark-cli-tool-title">
					<div>
						<h3>Lark CLI 下载与启用</h3>
						<p>默认从 npm 安装官方 `@larksuite/cli` 到项目本地目录，并自动写入 `LARK_CLI_PATH`。</p>
					</div>
					<span>{cliBusy ? "处理中" : "npm 本地安装"}</span>
				</div>
				<div className="lark-cli-tool-grid">
					<RuntimeInput
						label="NPM_PACKAGE"
						value={cliForm.package_name}
						placeholder="@larksuite/cli"
						hint="官方包默认是 @larksuite/cli，安装后命令名为 lark-cli。"
						onChange={(value) => updateCliField("package_name", value)}
					/>
					<RuntimeInput
						label="NPM_REGISTRY"
						value={cliForm.registry_url}
						placeholder="留空使用默认 npm registry"
						hint="网络慢时可填团队允许的 npm 镜像地址。"
						onChange={(value) => updateCliField("registry_url", value)}
					/>
					<RuntimeInput
						label="ENABLE_PATH"
						value={cliForm.path}
						placeholder="lark-cli 或绝对路径"
						hint="已有 CLI 时可直接填写路径并启用。"
						onChange={(value) => updateCliField("path", value)}
					/>
					<RuntimeInput
						label="ENABLE_WORKDIR"
						value={cliForm.workdir}
						placeholder="./runtime/lark-cli"
						hint="可执行真实命令时使用的工作目录。"
						onChange={(value) => updateCliField("workdir", value)}
					/>
				</div>
				<div className="runtime-form-actions">
					<button
						type="button"
						className="secondary-button"
						disabled={loading || saving || cliBusy || !cliForm.path.trim()}
						onClick={() => onEnableCli({ path: cliForm.path, workdir: cliForm.workdir })}
					>
						启用此路径
					</button>
					<button
						type="button"
						className="primary-button"
						disabled={loading || saving || cliBusy || !cliForm.package_name.trim()}
						onClick={() => onInstallCli({ package_name: cliForm.package_name, registry_url: cliForm.registry_url })}
					>
						{cliBusy ? "下载中..." : "下载并启用"}
					</button>
				</div>
			</div>

			<div className="lark-account-tool">
				<div className="lark-cli-tool-title">
					<div>
						<h3>飞书帐号检测与自动配置</h3>
						<p>自动检查本机 `lark-cli` 配置和 OAuth 状态；需要你在浏览器中确认飞书授权。</p>
					</div>
					<span>{account?.authenticated ? "已登录" : accountBusy ? "检测中" : "待授权"}</span>
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
					<div>
						<dt>CLI 路径</dt>
						<dd>{account?.cli_path || "-"}</dd>
					</div>
				</div>

				<div className="lark-cli-tool-grid">
					<RuntimeInput
						label="AUTH_DOMAIN"
						value={accountForm.auth_domain}
						placeholder="im"
						hint="发消息至少需要 im；多个域可填 im,contact。"
						onChange={(value) => updateAccountField("auth_domain", value)}
					/>
					<label className="runtime-toggle">
						<input
							type="checkbox"
							checked={accountForm.use_recommend}
							onChange={(event) => updateAccountField("use_recommend", event.target.checked)}
						/>
						<span>使用推荐权限</span>
						<small>开启后用 `auth login --recommend`，适合一次性授权常用权限。</small>
					</label>
					<label className="runtime-toggle">
						<input
							type="checkbox"
							checked={accountForm.force_new_app}
							onChange={(event) => updateAccountField("force_new_app", event.target.checked)}
						/>
						<span>重新创建应用</span>
						<small>已有配置通常不用打开；只在应用配置异常时使用。</small>
					</label>
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
						{accountBusy ? "处理中..." : "自动配置并登录"}
					</button>
				</div>
			</div>

			<div className="runtime-check-grid">
				{data?.checks.map((item) => (
					<article className={`runtime-check-item runtime-check-item--${item.status}`} key={item.id}>
						<header>
							<strong>{item.label}</strong>
							<span>{statusLabel[item.status]}</span>
						</header>
						<code>{item.value || "-"}</code>
						<p>{item.hint}</p>
						{item.required ? <small>必需</small> : <small>CUA 可选</small>}
					</article>
				))}
			</div>

			<div className="setup-grid">
				<div>
					<h3>.env 字段</h3>
					<pre>{envEntries.map(([key, value]) => `${key}=${value}`).join("\n")}</pre>
				</div>
				<div>
					<h3>安装与启动</h3>
					<dl>
						{installEntries.map(([key, value]) => (
							<div key={key}>
								<dt>{key}</dt>
								<dd>
									<code>{value}</code>
								</dd>
							</div>
						))}
					</dl>
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

function clearStorage(key: string) {
	if (typeof window === "undefined") {
		return;
	}
	try {
		window.localStorage.removeItem(key);
	} catch {
		// Local storage can be unavailable in restricted containers.
	}
}
