import logging
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import anomalies, analytics_routes, auth, export, funnel, heatmap, health, ingestion, metrics, videos, websocket
from app.cleanup import create_scheduler

# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Lifespan: start/stop the cleanup scheduler
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("cleanup_scheduler_started")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("cleanup_scheduler_stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Store Intelligence API", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware: Trace ID injection + request logging
# ---------------------------------------------------------------------------
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        start = time.monotonic()
        response = await call_next(request)
        latency_ms = round((time.monotonic() - start) * 1000, 2)

        response.headers["X-Trace-ID"] = trace_id

        logger.info(
            "request",
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        structlog.contextvars.clear_contextvars()
        return response


app.add_middleware(TraceIDMiddleware)


# ---------------------------------------------------------------------------
# Middleware: Deprecation header for legacy (non-/api/v1/) endpoints
# ---------------------------------------------------------------------------
class DeprecationHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/v1/"):
            response.headers["X-API-Deprecation"] = (
                "This endpoint is deprecated. Please migrate to /api/v1/"
            )
        return response


app.add_middleware(DeprecationHeaderMiddleware)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    logger.error("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"trace_id": trace_id, "message": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(ingestion.router)
app.include_router(metrics.router)
app.include_router(funnel.router)
app.include_router(heatmap.router)
app.include_router(anomalies.router)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(analytics_routes.router)
app.include_router(websocket.router)
app.include_router(export.router)
