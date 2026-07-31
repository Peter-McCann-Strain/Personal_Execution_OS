"""Application-specific exceptions. Fail loudly, no silent swallowing."""

from pydantic import BaseModel


class AppError(Exception):
    """Base exception for all application errors."""


class ConfigError(AppError):
    """Missing or invalid configuration."""


class LLMError(AppError):
    """LLM API call failed. No fallback — surface the real error."""


class DatabaseError(AppError):
    """Database operation failed."""


class TelegramError(AppError):
    """Telegram API interaction failed."""


class RoutingError(AppError):
    """Supervisor could not classify intent."""


class SearchError(AppError):
    """Search operation failed."""


class MCPError(AppError):
    """MCP (Model Context Protocol) operation failed."""


class NotFoundError(AppError):
    """Requested resource was not found."""


class EmbeddingError(AppError):
    """Embedding generation failed (e.g. Ollama unavailable)."""


class EvaluationError(AppError):
    """Evaluation pipeline failed. Auto-judge or quality check error."""


class ConnectorError(AppError):
    """Base class for external-connector failures (Gmail, Calendar, etc.).

    Subclasses describe *why* the call failed so callers (e.g. the dashboard)
    can surface a category-specific, actionable message instead of a generic
    "could not be loaded" string. No silent swallowing — every failure must
    map to one of these categories.
    """

    #: Machine-readable category. Subclasses override.
    category: str = "unknown"
    #: True when the user can fix this themselves (e.g. reconnect OAuth).
    actionable: bool = False
    #: Connector identifier ("gmail", "calendar", ...). Set by the call site.
    connector: str | None = None

    def __init__(
        self,
        message: str,
        *,
        connector: str | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.connector = connector
        self.original = original


class ConnectorTokenExpiredError(ConnectorError):
    """OAuth refresh failed or access was revoked. User must reconnect."""

    category = "token_expired"
    actionable = True


class ConnectorRateLimitedError(ConnectorError):
    """Provider returned 429. Transient — retry later."""

    category = "rate_limited"
    actionable = False


class ConnectorBackendError(ConnectorError):
    """Provider returned 5xx. Outage on their side."""

    category = "backend_error"
    actionable = False


class ConnectorUnknownError(ConnectorError):
    """Catch-all wrapping the original exception. Always logged with traceback."""

    category = "unknown"
    actionable = False


class ErrorResponse(BaseModel):
    """Standardised error response returned by all exception handlers."""

    error: str  # machine-readable code, e.g. "llm_error", "not_found"
    message: str  # human-readable description
    request_id: str | None = None  # correlation to request


# Map AppError subclasses to HTTP status codes and error codes.
EXCEPTION_STATUS_MAP: dict[type[AppError], tuple[int, str]] = {
    LLMError: (502, "llm_error"),
    DatabaseError: (503, "database_error"),
    TelegramError: (502, "telegram_error"),
    RoutingError: (422, "routing_error"),
    SearchError: (500, "search_error"),
    ConfigError: (500, "config_error"),
    MCPError: (502, "mcp_error"),
    NotFoundError: (404, "not_found"),
    EmbeddingError: (502, "embedding_error"),
    EvaluationError: (500, "evaluation_error"),
    ConnectorTokenExpiredError: (503, "connector_token_expired"),
    ConnectorRateLimitedError: (429, "connector_rate_limited"),
    ConnectorBackendError: (503, "connector_backend_error"),
    ConnectorUnknownError: (503, "connector_error"),
    ConnectorError: (503, "connector_error"),
}


_SAFE_ERROR_MESSAGES: dict[type[AppError], str] = {
    LLMError: "Something went wrong while generating the response.",
    DatabaseError: "A storage dependency was unavailable while handling that request.",
    TelegramError: "Telegram delivery failed while handling that request.",
    RoutingError: "I couldn't determine the right handling path for that request.",
    SearchError: "A search dependency failed while handling that request.",
    ConfigError: "A required service is not configured correctly.",
    MCPError: "A tool dependency failed while handling that request.",
    NotFoundError: "The requested resource was not found.",
    EmbeddingError: "A retrieval dependency failed while handling that request.",
    EvaluationError: "A quality-check dependency failed while handling that request.",
    ConnectorTokenExpiredError: "An external account needs to be reconnected.",
    ConnectorRateLimitedError: "An external service is rate limited. Try again later.",
    ConnectorBackendError: "An external service is currently unavailable.",
    ConnectorUnknownError: "An external connector failed while handling that request.",
    ConnectorError: "An external connector failed while handling that request.",
}


def user_safe_error_message(exc: AppError) -> str:
    """Return a user-safe message that never includes raw internal exception text."""
    for exc_type, message in _SAFE_ERROR_MESSAGES.items():
        if isinstance(exc, exc_type):
            return message
    return "An internal error occurred while handling that request."
