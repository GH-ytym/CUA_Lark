const quickCommands = ["帮我给项目群发今日进展", "把明天10点的会同步到日程", "整理最近文档并生成摘要"];

export function CommandComposer() {
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
			/>

			<div className="quick-command-list" aria-label="快捷指令示例">
				{quickCommands.map((command) => (
					<button type="button" className="quick-command" key={command}>
						{command}
					</button>
				))}
			</div>

			<div className="composer-actions">
				<button type="button" className="secondary-button">
					保存草稿
				</button>
				<button type="button" className="primary-button">
					提交任务
				</button>
			</div>
		</section>
	);
}
