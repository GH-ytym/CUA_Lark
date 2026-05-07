import { useEffect, useRef, useState } from "react";
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

const STREAM_EVENTS = ["snapshot", "step", "status", "heartbeat", "terminal"] as const;
const POLL_INTERVAL_MS = 2000;
const RECONNECT_DELAY_MS = 1200;
const MAX_RECONNECTS = 2;

export function useExecutionStream({
	taskId,
	enabled = true,
	onEvent,
	onDetail,
}: UseExecutionStreamOptions): ExecutionStreamState {
	const [connected, setConnected] = useState(false);
	const [error, setError] = useState("");
	const onEventRef = useRef(onEvent);
	const onDetailRef = useRef(onDetail);

	useEffect(() => {
		onEventRef.current = onEvent;
		onDetailRef.current = onDetail;
	}, [onDetail, onEvent]);

	useEffect(() => {
		if (!enabled || !taskId) {
			setConnected(false);
			setError("");
			return;
		}

		let closed = false;
		let source: EventSource | null = null;
		let pollTimer: number | undefined;
		let reconnectTimer: number | undefined;
		let reconnects = 0;

		async function refreshDetail() {
			try {
				const detail = await getExecutionDetail(taskId);
				if (!closed) {
					onDetailRef.current(detail);
					if (isTerminalStatus(detail.status) && typeof pollTimer !== "undefined") {
						window.clearInterval(pollTimer);
						pollTimer = undefined;
					}
				}
			} catch (detailError) {
				if (!closed) {
					setError(detailError instanceof Error ? detailError.message : "详情刷新失败");
				}
			}
		}

		function startPolling() {
			if (typeof pollTimer !== "undefined") {
				return;
			}
			void refreshDetail();
			pollTimer = window.setInterval(() => {
				void refreshDetail();
			}, POLL_INTERVAL_MS);
		}

		function stopPolling() {
			if (typeof pollTimer !== "undefined") {
				window.clearInterval(pollTimer);
				pollTimer = undefined;
			}
		}

		function handleMessage(message: MessageEvent<string>) {
			try {
				const event = JSON.parse(message.data) as ExecutionStreamEvent;
				onEventRef.current(event);
				if (event.detail) {
					onDetailRef.current(event.detail);
				}
				if (event.event !== "heartbeat") {
					void refreshDetail();
				}
				if (event.event === "terminal") {
					setConnected(false);
					stopPolling();
					source?.close();
				}
			} catch {
				setError("状态流解析失败");
			}
		}

		function openStream() {
			source?.close();
			source = new EventSource(getExecutionStreamUrl(taskId));
			source.addEventListener("open", () => {
				if (!closed) {
					setConnected(true);
					setError("");
					stopPolling();
				}
			});
			for (const eventName of STREAM_EVENTS) {
				source.addEventListener(eventName, handleMessage as EventListener);
			}
			source.addEventListener("error", () => {
				if (closed) {
					return;
				}
				setConnected(false);
				setError("状态流连接中断，已启用详情轮询兜底");
				source?.close();
				startPolling();
				if (reconnects >= MAX_RECONNECTS) {
					return;
				}
				reconnects += 1;
				reconnectTimer = window.setTimeout(openStream, RECONNECT_DELAY_MS);
			});
		}

		startPolling();
		openStream();

		return () => {
			closed = true;
			setConnected(false);
			stopPolling();
			if (typeof reconnectTimer !== "undefined") {
				window.clearTimeout(reconnectTimer);
			}
			source?.close();
		};
	}, [enabled, taskId]);

	return { connected, error };
}

function isTerminalStatus(status: ExecutionDetailResponse["status"]): boolean {
	return status === "completed" || status === "failed" || status === "canceled";
}
