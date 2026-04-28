const detailItems = [
	["链路 ID", "trace-demo-0425"],
	["当前阶段", "CLI 执行中"],
	["失败回退", "权限不足 / 页面控件缺失时进入 CUA"],
	["下一步", "流式刷新、失败重试、详情页"],
];

export function ResultDetail() {
	return (
		<section className="panel result" aria-labelledby="result-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">04 · 结果详情</p>
					<h2 id="result-title">执行详情占位</h2>
				</div>
				<span className="wire-tag">Detail</span>
			</div>

			<dl className="detail-grid">
				{detailItems.map(([label, value]) => (
					<div key={label}>
						<dt>{label}</dt>
						<dd>{value}</dd>
					</div>
				))}
			</dl>
		</section>
	);
}
