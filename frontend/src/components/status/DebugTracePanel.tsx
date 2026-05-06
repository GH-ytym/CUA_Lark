import type { DebugTraceItem } from "../../types/execution";

type DebugTracePanelProps = {
	items: DebugTraceItem[];
	query: string;
	onQueryChange: (value: string) => void;
};

const statusText: Record<DebugTraceItem["status"], string> = {
	queued: "排队",
	parsing: "解析",
	cli_running: "CLI",
	cli_failed: "CLI失败",
	cua_running: "CUA",
	completed: "完成",
	failed: "失败",
	canceled: "取消",
};

export function DebugTracePanel({ items, query, onQueryChange }: DebugTracePanelProps) {
	const normalizedQuery = query.trim().toLowerCase();
	const filteredItems = normalizedQuery
		? items.filter((item) =>
				`${item.name} ${item.summary} ${item.payload} ${item.status}`.toLowerCase().includes(normalizedQuery),
			)
		: items;

	return (
		<section className="panel debug-panel" aria-labelledby="debug-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">10 · 调试视图</p>
					<h2 id="debug-title">轨迹面板</h2>
				</div>
				<span className="wire-tag">Trace</span>
			</div>
			<label className="sr-only" htmlFor="trace-filter">
				筛选轨迹
			</label>
			<input
				id="trace-filter"
				className="trace-filter"
				value={query}
				placeholder="筛选步骤、状态、错误码"
				onChange={(event) => onQueryChange(event.target.value)}
			/>
			<div className="trace-list">
				{filteredItems.length === 0 ? <p className="empty-state">暂无匹配轨迹。</p> : null}
				{filteredItems.map((item) => (
					<article className="trace-item" key={item.id}>
						<header>
							<strong>{item.name}</strong>
							<span>{statusText[item.status]}</span>
						</header>
						<p>{item.summary}</p>
						<footer>
							<time>{item.createdAt}</time>
							<code>{item.payload}</code>
						</footer>
					</article>
				))}
			</div>
		</section>
	);
}
