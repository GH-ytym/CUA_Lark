type ErrorStateProps = {
	title: string;
	description: string;
	actionHint: string;
	severity?: "info" | "warning" | "danger";
	onRefresh: () => void;
	onRetry: () => void;
	onCancel: () => void;
	canCancel: boolean;
	disabled?: boolean;
};

export function ErrorState({
	title,
	description,
	actionHint,
	severity = "info",
	onRefresh,
	onRetry,
	onCancel,
	canCancel,
	disabled = false,
}: ErrorStateProps) {
	return (
		<section className={`panel error-state error-state--${severity}`} aria-labelledby="error-state-title">
			<div className="panel-title-row">
				<div>
					<p className="section-kicker">08 · 异常处理</p>
					<h2 id="error-state-title">{title}</h2>
				</div>
				<span className="wire-tag">Actions</span>
			</div>
			<p>{description}</p>
			<p className="action-hint">{actionHint}</p>
			<div className="composer-actions">
				<button type="button" className="secondary-button" onClick={onRefresh} disabled={disabled}>
					刷新详情
				</button>
				<button type="button" className="secondary-button" onClick={onCancel} disabled={disabled || !canCancel}>
					取消任务
				</button>
				<button type="button" className="primary-button" onClick={onRetry} disabled={disabled}>
					重试
				</button>
			</div>
		</section>
	);
}
