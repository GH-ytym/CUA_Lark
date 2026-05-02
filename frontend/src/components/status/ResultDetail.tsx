type DetailItem = [string, string];

type ResultDetailProps = {
	title: string;
	items: DetailItem[];
};

export function ResultDetail({ title, items }: ResultDetailProps) {
	return (
		<section className="panel result" aria-labelledby="result-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">04 · 结果详情</p>
					<h2 id="result-title">{title}</h2>
				</div>
				<span className="wire-tag">Detail</span>
			</div>

			<dl className="detail-grid">
				{items.map(([label, value]) => (
					<div key={label}>
						<dt>{label}</dt>
						<dd>{value}</dd>
					</div>
				))}
			</dl>
		</section>
	);
}
