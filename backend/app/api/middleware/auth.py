"""Authentication middleware for internal and Feishu-originated calls."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate incoming token and attach lightweight principal context."""

    SAFE_PATH_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith(self.SAFE_PATH_PREFIXES):
            return await call_next(request)

        settings = get_settings()
        if settings.app_env.lower() == "development":
            return await call_next(request)

        bearer = request.headers.get("authorization", "")
        app_token = request.headers.get("x-app-token", "")
        token = bearer.removeprefix("Bearer ").strip() if bearer else app_token.strip()
        valid_tokens = {settings.internal_api_token, settings.feishu_app_link_token}
        valid_tokens.discard("")

        if token not in valid_tokens:
            return JSONResponse(
                status_code=401,
                content={"code": "UNAUTHORIZED", "message": "Missing or invalid auth token."},
            )

        request.state.principal = "trusted-client"
        return await call_next(request)
