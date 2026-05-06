# C Line Frontend Handoff

## Scope

This handoff closes the C-line frontend/integration checklist against the current `main` branch.

## Delivered

- Day 1-5: sidebar layout, command input, task cards, timeline, result detail.
- Day 6: SSE stream subscription, manual refresh, retry entry.
- Day 7: frontend wired to `/api/agent/execute`, `/api/executions/{task_id}`, and `/api/executions/{task_id}/stream`.
- Day 8: actionable abnormal states for stream errors, failed tasks, cancellation, and confirmation.
- Day 9: reduced rerender surface through API/store/page separation and derived view models.
- Day 10: trace panel with step search/filter, task ID, capability, error code, and latest event details.
- Day 11: frontend smoke script for submit -> detail -> stream verification.
- Day 12: high-priority integration gaps fixed for missing stream, refresh fallback, and error display.
- Day 13: demo mode with larger status emphasis.
- Day 14: this release note documents reproduction steps and fallback behavior.

## Verify

```bash
npm run typecheck --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m pytest backend/tests
```

With the backend running:

```bash
npm run smoke --prefix frontend
```

## Runtime Notes

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`
- Configure `DASHSCOPE_API_KEY` and `lark-cli` for real Feishu end-to-end execution.
- Without those credentials/tools, the UI still verifies the integration contract and displays the backend failure state.
