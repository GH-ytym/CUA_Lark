import type { TimelineStep } from "../../types/execution";

const steps: TimelineStep[] = [
	{ id: "parse", label: "解析", detail: "识别意图、参数与风险词", status: "done" },
	{ id: "route", label: "路由", detail: "优先选择 CLI 精确执行", status: "done" },
	{ id: "execute", label: "执行", detail: "展示队列、运行与失败原因", status: "active" },
	{ id: "verify", label: "校验", detail: "结果回传并支持查看详情", status: "pending" },
];

export function StatusTimeline() {
	return (
		<section className="panel timeline" aria-labelledby="timeline-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">03 · 状态流</p>
					<h2 id="timeline-title">排队 / 执行 / CUA / 完成</h2>
				</div>
				<span className="wire-tag">Timeline</span>
			</div>

			<ol className="timeline-list">
				{steps.map((step) => (
					<li className={`timeline-step timeline-step--${step.status}`} key={step.id}>
						<span className="timeline-dot" aria-hidden="true" />
						<div>
							<strong>{step.label}</strong>
							<p>{step.detail}</p>
						</div>
					</li>
				))}
			</ol>
		</section>
	);
}
