const quickCommands = ["帮我给项目群发今日进展", "给梅家济发送：今天18:00前提交周报", "发消息给 cua lark 4：上线窗口顺延30分钟"];

type CommandComposerProps = {
	value: string;
	disabled?: boolean;
	onChange: (value: string) => void;
	onSubmit: () => void;
};

export function CommandComposer({ value, disabled = false, onChange, onSubmit }: CommandComposerProps) {
	return (
		<section className="panel composer" aria-labelledby="composer-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">01 · 指令入口</p>
					<h2 id="composer-title">告诉智能体要做什么</h2>
				</div>
				<span className="wire-tag">Chat Input</span>
			</div>

			<label className="sr-only" htmlFor="command-input">
				自然语言指令
			</label>
			<textarea
				id="command-input"
				placeholder="例如：帮我给产品群发送今天 18:00 的联调提醒，并在失败时改用 CUA 接管。"
				rows={4}
				value={value}
				disabled={disabled}
				onChange={(event) => onChange(event.target.value)}
			/>

			<div className="quick-command-list" aria-label="快捷指令示例">
				{quickCommands.map((command) => (
					<button
						type="button"
						className="quick-command"
						key={command}
						onClick={() => onChange(command)}
						disabled={disabled}
					>
						{command}
					</button>
				))}
			</div>

			<div className="composer-actions">
				<button type="button" className="secondary-button" onClick={() => onChange("")} disabled={disabled}>
					清空
				</button>
				<button type="button" className="primary-button" onClick={onSubmit} disabled={disabled || !value.trim()}>
					{disabled ? "提交中..." : "提交任务"}
				</button>
			</div>
		</section>
	);
}
