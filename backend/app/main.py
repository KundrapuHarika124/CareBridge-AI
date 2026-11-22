"""CareBridge AI backend entry point."""
import asyncio
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, appointments, assistant, auth, care, directory, health, superadmin
from app.core.config import get_settings
from app.core.errors import AppError, error_body
from app.services import jobs

settings = get_settings()


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Only an allow-list of fields is ever logged."""

    FIELDS = ("request_id", "user_id", "method", "path", "status", "duration_ms", "reason")

    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for key in self.FIELDS:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())


log = logging.getLogger("carebridge.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.validate_runtime()
    task = None
    if settings.run_jobs and settings.app_env != "test":
        task = asyncio.create_task(jobs.loop())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="CareBridge AI API",
    version="0.1.0",
    description="Prototype healthcare appointment coordination API. Synthetic data only. Not for clinical use.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id, log one line per request, and never leak internals on errors."""
    request.state.request_id = uuid.uuid4().hex
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled_error", extra={"request_id": request.state.request_id, "path": request.url.path})
        response = JSONResponse(
            status_code=500,
            content=error_body(request, "INTERNAL_ERROR", "Something went wrong. Please try again."),
        )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    log.info(
        "request",
        extra={
            "request_id": request.state.request_id,
            "user_id": getattr(request.state, "user_id", None),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(error_body(request, exc.code, exc.message, exc.details)),
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": str(err.get("msg", ""))}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=400, content=error_body(request, "VALIDATION_ERROR", "Please check the form.", details))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=error_body(request, code, "Request could not be handled."))


@app.exception_handler(OperationalError)
async def database_down_handler(request: Request, exc: OperationalError):
    # The database is unreachable: say so plainly, and never report or queue a success.
    log.error("database_unavailable", extra={"request_id": getattr(request.state, "request_id", None)})
    return JSONResponse(
        status_code=503,
        content=error_body(request, "DATABASE_UNAVAILABLE", "The service is temporarily unavailable. Nothing was saved."),
    )


for module in (health, auth, care, directory, appointments, assistant, superadmin, admin):
    app.include_router(module.router, prefix="/api/v1")
