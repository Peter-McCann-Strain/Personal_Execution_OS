"""Structured logging configuration with structlog."""

import logging
import sys

import structlog

from src.app.core.pii_redactor import (
    build_pii_redact_processor,
    compile_override_patterns,
    parse_allowlist_keys,
)

_SENSITIVE_EXCEPTION_KEYS = frozenset(
    {
        "detail",
        "error",
        "error_message",
        "exception",
        "stack",
        "traceback",
        "traceback_text",
    }
)


def safe_exception_processor(_logger, _method_name: str, event_dict: dict) -> dict:
    """Remove exception messages and tracebacks before any external log sink."""
    exc_info = event_dict.pop("exc_info", None)
    if isinstance(exc_info, BaseException):
        event_dict.setdefault("error_class", type(exc_info).__name__)
    elif isinstance(exc_info, tuple) and exc_info:
        exc_type = exc_info[0]
        if isinstance(exc_type, type):
            event_dict.setdefault("error_class", exc_type.__name__)

    for key in _SENSITIVE_EXCEPTION_KEYS:
        if key in event_dict:
            event_dict[key] = "[redacted-exception]"
    return event_dict


def setup_logging(log_level: str, app_env: str) -> None:
    """Configure structlog. JSON in production, colored console in dev.

    Inserts a PII redaction processor immediately before the final renderer
    so every log line (dev console or prod JSON) has emails, phone numbers,
    postcodes, credit-card shapes and caller-supplied override patterns
    redacted. See :mod:`src.app.core.pii_redactor`.
    """

    # Settings are imported lazily so this module stays cheap to import in
    # test contexts that don't populate env vars.
    from src.app.config import get_settings

    try:
        settings = get_settings()
        pii_enabled = bool(getattr(settings, "pii_redaction_enabled", True))
        overrides = compile_override_patterns(
            getattr(settings, "pii_override_patterns", []),
        )
        allowlist = parse_allowlist_keys(
            getattr(settings, "pii_allowlist_keys", []),
        )
    except Exception:
        # Never let logging setup fail because settings are in flux.
        # Fall through to safe defaults — redaction still on.
        pii_enabled = True
        overrides = []
        allowlist = None  # type: ignore[assignment]

    pii_processor = build_pii_redact_processor(
        enabled=pii_enabled,
        override_patterns=overrides,
        allowlist_keys=allowlist,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        structlog.processors.UnicodeDecoder(),
    ]

    if app_env == "production":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # PII redaction MUST run after all dict-mutating processors (e.g.
    # CallsiteParameterAdder, exception formatting) but BEFORE the
    # terminal renderer so the final JSON / console line is scrubbed.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            safe_exception_processor,
            pii_processor,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
