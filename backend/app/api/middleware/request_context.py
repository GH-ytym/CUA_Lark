"""Request context middleware for correlation and latency headers."""

from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach request metadata and return tracing headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started_at = perf_counter()
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        duration_ms = (perf_counter() - started_at) * 1000
        response.headers["x-request-id"] = request_id
        response.headers["x-process-time-ms"] = f"{duration_ms:.2f}"
        return response
