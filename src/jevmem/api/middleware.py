"""Request context, body-size limit, and rate limiting (ASGI middlewares)."""

from __future__ import annotations

import time
from collections import defaultdict
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from jevmem.observability.logging import get_logger, request_id_var, user_id_var

log = get_logger("api")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates X-Request-ID and logs one structured line per request (no bodies)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex
        token = request_id_var.set(request_id)
        user_token = user_id_var.set(request.query_params.get("user_id"))
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
            user_id_var.reset(user_token)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            return JSONResponse(
                {"error": "request_too_large", "max_bytes": self.max_bytes}, status_code=413
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client token bucket (in-process). A hook, not a distributed limiter."""

    def __init__(self, app: object, per_minute: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (self.capacity, time.monotonic())
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.capacity <= 0 or not request.url.path.startswith("/api/"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        tokens, last = self._buckets[client]
        now = time.monotonic()
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[client] = (tokens, now)
            return JSONResponse(
                {"error": "rate_limited"}, status_code=429, headers={"Retry-After": "5"}
            )
        self._buckets[client] = (tokens - 1.0, now)
        return await call_next(request)
