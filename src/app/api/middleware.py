"""FastAPI middleware — request logging, error handling.

Because ``BaseHTTPMiddleware`` catches exceptions *before* FastAPI's
``@app.exception_handler`` can fire, this middleware is the single source
of truth for mapping application exceptions to HTTP responses.  It uses
:data:`EXCEPTION_STATUS_MAP` to return correct status codes (502, 503,
404 …) instead of collapsing everything to 500.
"""

import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from src.app.core.exceptions import EXCEPTION_STATUS_MAP, AppError, DatabaseError, ErrorResponse

logger = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with a unique request ID, method, path, and duration.

    Catches all exceptions and maps them to structured JSON error responses
    with the correct HTTP status code via ``EXCEPTION_STATUS_MAP``.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.monotonic()

        try:
            response = await call_next(request)
        except AppError as exc:
            # Known application errors — map to correct HTTP status code
            status_code, error_code = EXCEPTION_STATUS_MAP.get(
                type(exc),
                (500, "app_error"),
            )
            logger.error(
                "app_error",
                error_code=error_code,
                error_class=type(exc).__name__,
                method=request.method,
                path=request.url.path,
            )
            body = ErrorResponse(
                error=error_code,
                message=str(exc),
                request_id=request_id,
            )
            return JSONResponse(
                status_code=status_code,
                content=body.model_dump(),
            )
        except RequestValidationError as exc:
            logger.warning(
                "validation_error",
                error_count=len(exc.errors()),
                method=request.method,
                path=request.url.path,
            )
            body = ErrorResponse(
                error="validation_error",
                message="Request validation failed",
                request_id=request_id,
            )
            return JSONResponse(status_code=422, content=body.model_dump())
        except Exception as exc:
            # Map SQLAlchemy errors to DatabaseError for proper 503 status
            try:
                from sqlalchemy.exc import SQLAlchemyError

                if isinstance(exc, SQLAlchemyError):
                    db_error = DatabaseError(f"Database error: {type(exc).__name__}")
                    status_code, error_code = EXCEPTION_STATUS_MAP[DatabaseError]
                    logger.error(
                        "database_error",
                        error_code=error_code,
                        error_class=type(exc).__name__,
                        method=request.method,
                        path=request.url.path,
                    )
                    body = ErrorResponse(
                        error=error_code,
                        message=str(db_error),
                        request_id=request_id,
                    )
                    return JSONResponse(
                        status_code=status_code,
                        content=body.model_dump(),
                    )
            except ImportError:
                pass

            logger.exception(
                "unhandled_error",
                method=request.method,
                path=request.url.path,
            )
            body = ErrorResponse(
                error="internal_error",
                message="An internal error occurred",
                request_id=request_id,
            )
            return JSONResponse(
                status_code=500,
                content=body.model_dump(),
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )

        response.headers["X-Request-ID"] = request_id

        return response
