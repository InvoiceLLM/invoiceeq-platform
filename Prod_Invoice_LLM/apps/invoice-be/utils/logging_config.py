import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variables for request correlation
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="")
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


class StructuredJsonFormatter(logging.Formatter):
    """
    Feature 19 (Task 19.3): Structured JSON Log Formatter.
    Formats log records into structured JSON suitable for Azure Log Analytics
    and Application Insights correlation.
    """

    def __init__(self, service_name: str = "invoice-be"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Inject context variables if present
        req_id = request_id_ctx.get()
        if req_id:
            log_obj["request_id"] = req_id

        tenant_id = tenant_id_ctx.get()
        if tenant_id:
            log_obj["tenant_id"] = tenant_id

        trace_id = trace_id_ctx.get()
        if trace_id:
            log_obj["trace_id"] = trace_id

        # Attach exception details if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Attach custom extra fields passed in logging calls
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_obj.update(record.extra_fields)

        return json.dumps(log_obj)


def setup_structured_logging(service_name: str = "invoice-be", log_level: str = "INFO") -> None:
    """Configures root logger with the structured JSON formatter on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter(service_name=service_name))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


class TracingAndLoggingMiddleware(BaseHTTPMiddleware):
    """
    Feature 19 (Task 19.3): Request Tracing & Correlation Middleware.
    Injects request_id and trace_id into contextvars and response headers,
    and logs duration of each request.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        # 1. Resolve or generate Request-ID
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_ctx.set(req_id)

        # 2. Extract OpenTelemetry Trace-ID if available
        trace_id = ""
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.get_span_context().is_valid:
                trace_id = format(span.get_span_context().trace_id, "032x")
        except Exception:
            pass

        if not trace_id:
            trace_id = request.headers.get("X-Trace-ID") or req_id

        trace_id_ctx.set(trace_id)

        # 3. Process Request
        response: Response
        try:
            response = await call_next(request)
        except Exception as ex:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logging.getLogger("access").error(
                f"HTTP {request.method} {request.url.path} - Exception: {ex}",
                extra={"extra_fields": {"duration_ms": duration_ms, "status_code": 500}},
            )
            raise ex

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 4. Attach headers to response for client-side tracing
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Trace-ID"] = trace_id

        # Skip noisy polling endpoints like /health in access logs
        if not request.url.path.startswith("/health"):
            logging.getLogger("access").info(
                f"HTTP {request.method} {request.url.path} {response.status_code} ({duration_ms}ms)",
                extra={"extra_fields": {"duration_ms": duration_ms, "status_code": response.status_code}},
            )

        return response
