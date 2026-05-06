import type { TaskCard } from "../../types/execution";

const statusLabel: Record<TaskCard["status"], string> = {
	queued: "排队中",
	running: "执行中",
	fallback: "CUA 接管",
	completed: "已完成",
	failed: "失败",
	canceled: "已取消",
};

type ExecutionFeedProps = {
	tasks: TaskCard[];
};

export function ExecutionFeed({ tasks }: ExecutionFeedProps) {
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
				{tasks.length === 0 ? <p className="empty-state">提交一条指令后，这里会显示解析与确认结果。</p> : null}
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
