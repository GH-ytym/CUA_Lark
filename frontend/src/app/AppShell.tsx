import type { ReactNode } from "react";

type AppShellProps = {
	children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
	return (
		<div className="app-shell">
			<header className="app-header" aria-label="CUA Lark sidebar header">
				<div>
					<p className="eyebrow">Feishu AI Challenge · Day 1</p>
					<h1>CUA-Lark 智能侧边栏</h1>
				</div>
				<span className="status-pill">线框评审版</span>
			</header>
			{children}
		</div>
	);
}
