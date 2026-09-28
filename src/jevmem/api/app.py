"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from jevmem import __version__
from jevmem.api.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
from jevmem.api.routes.core import router
from jevmem.bootstrap import App, build_app
from jevmem.config import Settings, get_settings
from jevmem.memory.service import OutOfOrderWriteError, ServiceError
from jevmem.memory.store import MemoryNotFoundError
from jevmem.observability.logging import get_logger, request_id_var

log = get_logger("api")

FRONTEND_DIST = Path("frontend/dist")


def create_app(settings: Settings | None = None, *, bundle: App | None = None) -> FastAPI:
    """`bundle` lets tests inject a prebuilt service (with fakes); otherwise one is built."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = bundle is None
        app_bundle = bundle or await build_app(settings)
        app.state.bundle = app_bundle
        app.state.service = app_bundle.service
        app.state.settings = settings
        app.state.benchmarks = {}
        try:
            yield
        finally:
            if owned:
                await app_bundle.aclose()

    app = FastAPI(
        title="JevMem",
        version=__version__,
        description="Decision-native long-term memory for AI agents.",
        lifespan=lifespan,
    )
    # Starlette runs the last-added middleware first.
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            {"error": code, "message": message, "request_id": request_id_var.get()},
            status_code=status,
        )

    @app.exception_handler(MemoryNotFoundError)
    async def _not_found(_: Request, exc: MemoryNotFoundError) -> JSONResponse:
        return error(404, "not_found", f"memory {exc.args[0]} not found")

    @app.exception_handler(OutOfOrderWriteError)
    async def _out_of_order(_: Request, exc: OutOfOrderWriteError) -> JSONResponse:
        return error(409, "out_of_order", str(exc))

    @app.exception_handler(ServiceError)
    async def _service(_: Request, exc: ServiceError) -> JSONResponse:
        return error(503, "service_unavailable", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"error": type(exc).__name__})
        return error(500, "internal_error", "internal server error")

    app.include_router(router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app
