import { useEffect, useState } from "react";
import { getExecutionDetail, getExecutionStreamUrl } from "../../lib/api";
import type { ExecutionDetailResponse, ExecutionStreamEvent } from "../../types/execution";

type UseExecutionStreamOptions = {
	taskId: string;
	enabled?: boolean;
	onEvent: (event: ExecutionStreamEvent) => void;
	onDetail: (detail: ExecutionDetailResponse) => void;
};

type ExecutionStreamState = {
	connected: boolean;
	error: string;
};

export function useExecutionStream({
	taskId,
	enabled = true,
	onEvent,
	onDetail,
}: UseExecutionStreamOptions): ExecutionStreamState {
	const [connected, setConnected] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		if (!enabled || !taskId) {
			setConnected(false);
			setError("");
			return;
		}

		let closed = false;
		let source: EventSource | null = null;

		async function refreshDetail() {
			try {
				const detail = await getExecutionDetail(taskId);
				if (!closed) {
					onDetail(detail);
				}
			} catch (detailError) {
				if (!closed) {
					setError(detailError instanceof Error ? detailError.message : "详情刷新失败");
				}
			}
		}

		function handleMessage(message: MessageEvent<string>) {
			try {
				const event = JSON.parse(message.data) as ExecutionStreamEvent;
				onEvent(event);
				if (event.detail) {
					onDetail(event.detail);
				}
				if (event.event === "terminal") {
					setConnected(false);
					source?.close();
				}
			} catch {
				setError("状态流解析失败");
			}
		}

		void refreshDetail();
		source = new EventSource(getExecutionStreamUrl(taskId));
		source.addEventListener("open", () => {
			if (!closed) {
				setConnected(true);
				setError("");
			}
		});
		source.addEventListener("snapshot", handleMessage as EventListener);
		source.addEventListener("step", handleMessage as EventListener);
		source.addEventListener("terminal", handleMessage as EventListener);
		source.addEventListener("error", () => {
			if (closed) {
				return;
			}
			setConnected(false);
			setError("状态流连接中断，已刷新任务详情");
			void refreshDetail();
			source?.close();
		});

		return () => {
			closed = true;
			setConnected(false);
			source?.close();
		};
	}, [enabled, onDetail, onEvent, taskId]);

	return { connected, error };
}
