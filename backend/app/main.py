"""FastAPI entrypoint for CUA-Lark backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.request_context import RequestContextMiddleware
from app.api.routes import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """Create and configure FastAPI app instance."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router)
    return app


app = create_app()
