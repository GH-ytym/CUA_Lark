import type { TimelineStep } from "../../types/execution";

type StatusTimelineProps = {
	steps: TimelineStep[];
};

export function StatusTimeline({ steps }: StatusTimelineProps) {
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
