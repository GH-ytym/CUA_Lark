import type { TaskCard } from "../../types/execution";

const tasks: TaskCard[] = [
	{
		id: "task-001",
		title: "发送群提醒",
		description: "解析自然语言 → 映射 Lark-CLI 消息命令 → 等待执行结果。",
		status: "running",
		owner: "CLI",
		duration: "00:18",
	},
	{
		id: "task-002",
		title: "日程冲突处理",
		description: "CLI 返回权限不足，计划切换至 CUA 视觉保底流程。",
		status: "fallback",
		owner: "CUA",
		duration: "01:04",
	},
];

const statusLabel: Record<TaskCard["status"], string> = {
	queued: "排队中",
	running: "执行中",
	fallback: "CUA 接管",
	completed: "已完成",
	failed: "失败",
};

export function ExecutionFeed() {
	return (
		<section className="panel feed" aria-labelledby="feed-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">02 · 任务卡片</p>
					<h2 id="feed-title">实时任务流</h2>
				</div>
				<span className="wire-tag">Task Cards</span>
			</div>

			<div className="task-list">
				{tasks.map((task) => (
					<article className={`task-card task-card--${task.status}`} key={task.id}>
						<div className="task-card__header">
							<strong>{task.title}</strong>
							<span>{statusLabel[task.status]}</span>
						</div>
						<p>{task.description}</p>
						<footer>
							<span>执行器：{task.owner}</span>
							<span>耗时：{task.duration}</span>
						</footer>
					</article>
				))}
			</div>
		</section>
	);
}
