import type { ReactNode } from "react";

type AppShellProps = {
	children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
	return (
		<div className="app-shell">
			<header className="app-header" aria-label="CUA Lark sidebar header">
				<div>
					<p className="eyebrow">Feishu AI Challenge · C Line</p>
					<h1>CUA-Lark 智能侧边栏</h1>
				</div>
				<span className="status-pill">集成封板版</span>
			</header>
			{children}
		</div>
	);
}
