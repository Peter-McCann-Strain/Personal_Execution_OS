"""Shared LLM response utilities.

Key behaviours
--------------
* Every call to call_llm / call_and_parse / call_and_extract_text automatically
  prepends the current date/time in the user's configured timezone so agents
  always have temporal awareness.

* Transient error retry: 5 attempts with exponential backoff (2 s → 30 s) on
  RateLimitError, APIConnectionError, and InternalServerError.

* Parse retry with feedback: call_and_parse_with_retry re-submits the
  malformed JSON back to the model with a correction prompt, giving it up to 5
  full attempts to produce valid output. LLMs typically self-correct within 2
  retries when shown what was wrong.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic
import httpx
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.core.exceptions import LLMError
from src.app.core.llm.provider import BaseLLMProvider
from src.app.core.llm_pricing import estimate_cost, price_table_version
from src.app.core.otel import bind_request_id, get_tracer
from src.app.core.personality import get_personality_prefix
from src.app.core.pii_redactor import redact
from src.app.core.response_style import get_response_style_prefix

logger_retry = logging.getLogger("llm_retry")
logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)
LLMClient = AsyncAnthropic | BaseLLMProvider

# Type alias for the system prompt: callers may pass a plain string (auto-wrapped
# with cache_control) or a pre-built list of content blocks.
SystemPrompt = str | list[dict]

# Extended thinking API (April 2026 spec).
# `thinking={"type":"enabled","budget_tokens":N}` is DEPRECATED on Opus 4.6 /
# Sonnet 4.6 and returns HTTP 400 on Opus 4.7. The current contract is
# `thinking={"type":"adaptive"}` + `output_config={"effort":<level>}`.
# `max_tokens` remains the hard cap; thinking tokens are billed as output.
# Effort levels, in ascending cost/quality: low, medium, high, xhigh, max.
Effort = Literal["low", "medium", "high", "xhigh", "max"]
ThinkingMode = Literal["adaptive", "disabled"]

_MAX_PARSE_RETRIES = 5  # total attempts (1 initial + 4 correction passes)
_MAX_TRANSIENT_RETRIES = 5  # retry on rate-limit / connection errors


def _build_thinking_kwargs(
    *,
    effort: Effort | None,
    thinking_mode: ThinkingMode | None,
    output_config: dict | None,
) -> dict:
    """Translate the caller-friendly ``effort``/``thinking_mode`` args into the
    Anthropic SDK's ``thinking`` + ``output_config`` pair.

    Rules
    -----
    * If ``effort`` is set, thinking defaults to "adaptive" unless the caller
      explicitly passed ``thinking_mode="disabled"``.
    * If ``thinking_mode="disabled"`` is passed, ``thinking={"type":"disabled"}``
      is emitted and ``output_config.effort`` is still honoured (per April 2026
      spec, effort applies with or without thinking).
    * If ``output_config`` is also provided, its keys are merged on top of the
      derived defaults so callers can add ``format``/``stop_sequences``/etc.
    * **Never** emits ``budget_tokens`` — that field is deprecated on Opus 4.6 /
      Sonnet 4.6 and rejected (400) on Opus 4.7.
    """
    kwargs: dict = {}
    derived_output_config: dict = {}

    if effort is not None:
        derived_output_config["effort"] = effort
        # Default to adaptive when effort is requested; allow explicit disable.
        kwargs["thinking"] = {"type": thinking_mode or "adaptive"}
    elif thinking_mode is not None:
        kwargs["thinking"] = {"type": thinking_mode}

    # Caller-supplied output_config wins on conflicting keys.
    merged = {**derived_output_config, **output_config} if output_config else derived_output_config

    if merged:
        kwargs["output_config"] = merged

    return kwargs


def _current_request_id() -> str | None:
    """Fetch the request_id bound to the structlog contextvars (if any).

    Kept as a thin helper so the OTel span attribute can correlate with
    the app's own request_id (set by RequestLoggingMiddleware or by the
    ARQ worker in process_agent_task).
    """
    try:
        ctx = structlog.contextvars.get_contextvars()
    except Exception:
        return None
    value = ctx.get("request_id")
    return value if isinstance(value, str) and value else None


def _pii_redaction_enabled() -> bool:
    """Respect the ``pii_redaction_enabled`` setting for span events.

    Default True (fail-safe). If settings can't be resolved (module-load
    time, tests without env setup) we assume redaction is on so we never
    accidentally ship raw prompt content to a Collector.
    """
    try:
        from src.app.config import get_settings

        return bool(get_settings().pii_redaction_enabled)
    except Exception:
        return True


def _otel_content_export_enabled() -> bool:
    """Require a separate explicit opt-in before exporting model content."""
    try:
        from src.app.config import get_settings

        return bool(get_settings().otel_export_content)
    except Exception:
        return False


def _flatten_message_content(content: object) -> str:
    """Convert the Anthropic ``messages[i].content`` shape into a single string.

    Content can be a plain string, a list of blocks (``{"type":"text",...}``)
    or a list of dicts with cache_control wrappers. We stringify the text
    parts only and drop non-text blocks for event bodies (images are not
    useful in span events and would bloat the Collector).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and (block.get("type") == "text" or "text" in block):
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _set_genai_request_attrs(
    span,
    *,
    model: str,
    max_tokens: int,
    output_config: dict | None,
    thinking_mode: ThinkingMode | None,
    effort: Effort | None,
) -> None:
    """Apply GenAI request-side attributes to the active span."""
    try:
        span.set_attribute("gen_ai.system", "anthropic")
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))
        if output_config and "temperature" in output_config:
            span.set_attribute(
                "gen_ai.request.temperature",
                float(output_config["temperature"]),
            )
        if effort is not None:
            # No official attribute yet for effort — emit as a namespaced
            # extension so downstream dashboards can group by cost tier.
            span.set_attribute("gen_ai.request.thinking_mode", effort)
        elif thinking_mode is not None:
            span.set_attribute("gen_ai.request.thinking_mode", thinking_mode)
    except Exception:
        # Span-attr bookkeeping must never break the LLM call.
        logger.debug("otel_set_genai_request_attrs_failed", exc_info=True)


def _set_genai_response_attrs(
    span,
    *,
    fresh_input: int,
    output_tokens: int,
    cache_read: int,
    cache_create_total: int,
    cache_5m: int,
    cache_1h: int,
    cache_hit_rate: float,
    cost_usd: float,
    cost_gbp: float,
    duration_ms: int,
) -> None:
    """Apply GenAI response-side attributes (usage, cache, cost, latency)."""
    try:
        span.set_attribute("gen_ai.usage.input_tokens", int(fresh_input))
        span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
        # Anthropic-specific cache extensions — no standard yet (April 2026).
        span.set_attribute("anthropic.usage.cache_read_input_tokens", int(cache_read))
        span.set_attribute("anthropic.usage.cache_creation_input_tokens", int(cache_create_total))
        span.set_attribute("anthropic.usage.cache_creation_ephemeral_5m", int(cache_5m))
        span.set_attribute("anthropic.usage.cache_creation_ephemeral_1h", int(cache_1h))
        span.set_attribute("anthropic.cache_hit_rate", float(cache_hit_rate))
        # Cost extensions — no standard yet (April 2026).
        span.set_attribute("gen_ai.usage.cost_usd", float(cost_usd))
        span.set_attribute("gen_ai.usage.cost_gbp", float(cost_gbp))
        span.set_attribute("gen_ai.client.duration_ms", int(duration_ms))
    except Exception:
        logger.debug("otel_set_genai_response_attrs_failed", exc_info=True)


def _emit_genai_prompt_events(
    span,
    *,
    system,
    messages: list[dict],
    redact_pii: bool,
) -> None:
    """Emit the prompt as span EVENTS (never as attributes).

    April 2026 spec — content is kept out of the attribute layer so the
    Collector can drop it in a single processor. Event names follow the
    ``gen_ai.<role>.message`` convention.
    """
    try:
        # System message event.
        system_text = _flatten_message_content(system)
        if system_text:
            span.add_event(
                "gen_ai.system.message",
                attributes={
                    "gen_ai.system": "anthropic",
                    "content": (redact(system_text) if redact_pii else system_text),
                },
            )
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = _flatten_message_content(msg.get("content", ""))
            if not content:
                continue
            span.add_event(
                f"gen_ai.{role}.message",
                attributes={
                    "gen_ai.system": "anthropic",
                    "content": redact(content) if redact_pii else content,
                },
            )
    except Exception:
        logger.debug("otel_emit_genai_prompt_events_failed", exc_info=True)


def _emit_genai_completion_event(
    span,
    *,
    response,
    redact_pii: bool,
) -> None:
    """Emit the completion as a ``gen_ai.choice`` span event.

    Non-text content blocks (tool_use) are summarised; only textual
    completions have their content body attached.
    """
    try:
        parts: list[str] = []
        has_tool_use = False
        for block in getattr(response, "content", []) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", "") or ""
                if text:
                    parts.append(text)
            elif btype == "tool_use":
                has_tool_use = True
        body = "\n".join(parts)
        if redact_pii:
            body = redact(body)
        span.add_event(
            "gen_ai.choice",
            attributes={
                "gen_ai.system": "anthropic",
                "gen_ai.response.has_tool_use": has_tool_use,
                "content": body,
            },
        )
    except Exception:
        logger.debug("otel_emit_genai_completion_event_failed", exc_info=True)


def _record_span_exception(span, exc: BaseException) -> None:
    """Attach exception info to the span and mark status=ERROR.

    Telemetry bookkeeping is best-effort — we swallow all exceptions so
    a broken tracer can never turn into a failed LLM call.
    """
    with contextlib.suppress(Exception):
        # These methods exist on both the real OTel Span and our noop
        # fallback in core/otel.py.
        span.record_exception(RuntimeError(type(exc).__name__))
    with contextlib.suppress(Exception):
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR, description=type(exc).__name__))


def _current_datetime_preamble(user_timezone: str = "Europe/London") -> str:
    """Return a one-line datetime preamble for injection into every system prompt.

    Falls back to UTC if the timezone string is invalid so callers are never
    blocked by a misconfigured env var.
    """
    try:
        tz = ZoneInfo(user_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz=tz)
    return f"Current date and time: {now:%A %d %B %Y, %H:%M %Z}\n\n"


def _build_system_blocks(
    system: SystemPrompt,
    *,
    cache_system: bool,
) -> str | list[dict]:
    """Normalise the system prompt into the format expected by the Anthropic SDK.

    When *cache_system* is True and *system* is a plain string, wraps it in a
    content-block list with ``cache_control: {"type": "ephemeral"}`` so
    Anthropic's prompt caching can avoid re-processing the same system prompt
    across calls (~90% input-token savings on cache hits).

    If *system* is already a list of content blocks, it is returned as-is
    (the caller is responsible for cache_control in that case).

    When *cache_system* is False the original string is passed through
    unchanged so the SDK uses its default behaviour.
    """
    if isinstance(system, list):
        # Caller supplied pre-built content blocks — use them verbatim.
        return system

    if cache_system:
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    # No caching requested — pass the plain string.
    return system


@retry(
    retry=retry_if_exception_type(
        (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        )
    ),
    stop=stop_after_attempt(_MAX_TRANSIENT_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger_retry, logging.WARNING),
    reraise=True,
)
async def call_llm(
    client: LLMClient,
    *,
    model: str,
    max_tokens: int,
    system: SystemPrompt,
    messages: list[dict],
    timeout_seconds: float = 120.0,
    cache_system: bool = True,
    inject_personality: bool = True,
    inject_datetime: bool = True,
    user_timezone: str = "Europe/London",
    _tools: list[dict] | None = None,
    effort: Effort | None = None,
    thinking_mode: ThinkingMode | None = None,
    output_config: dict | None = None,
):
    """Call Claude with automatic retry on transient errors.

    Parameters
    ----------
    client:
        An ``AsyncAnthropic`` client instance.
    model:
        The Claude model ID (e.g. ``"claude-sonnet-4-6"``).
    max_tokens:
        Maximum output tokens.
    system:
        System prompt — either a plain string (auto-wrapped with
        ``cache_control`` for prompt caching) or a pre-built list of
        content blocks.
    messages:
        Conversation messages in Anthropic format.
    timeout_seconds:
        Request timeout passed to the SDK's ``timeout`` parameter.
    cache_system:
        When ``True`` (default) and *system* is a string, wraps the
        system prompt in a cacheable content block to leverage
        Anthropic's prompt caching (~90% input-token savings on
        repeated prompts).  Set to ``False`` to disable.
    inject_personality:
        When ``True`` (default), prepends the personality prefix from
        SOUL.md + IDENTITY.md to the system prompt. Set to ``False``
        for routing/classification calls that should stay focused.
    inject_datetime:
        When ``True`` (default), prepends the current date/time in the
        user's timezone so agents always have temporal awareness.
    user_timezone:
        IANA timezone string (default "Europe/London").  Falls back to
        UTC if the value is not a valid timezone.
    _tools:
        Optional list of tool definitions to pass as ``tools=`` to the
        Anthropic SDK (e.g. for MCP tool-calling). When ``None``
        (default), no tools are sent.
    effort:
        Extended-thinking effort level — one of
        ``{"low","medium","high","xhigh","max"}``. When provided, the call
        is sent with ``thinking={"type":"adaptive"}`` +
        ``output_config={"effort":<level>}`` (the April 2026 API shape).
        When ``None`` (default) no thinking fields are emitted and the
        model's default behaviour applies. Thinking tokens are billed
        as output tokens.
    thinking_mode:
        Override the thinking shape. ``"adaptive"`` is the default when
        ``effort`` is set; pass ``"disabled"`` to send
        ``thinking={"type":"disabled"}`` while still conveying an effort
        hint. ``budget_tokens`` is never emitted — it is deprecated on
        Opus 4.6 / Sonnet 4.6 and rejected (HTTP 400) on Opus 4.7.
    output_config:
        Optional dict merged on top of the derived ``output_config``.
        Use for ``format``/``stop_sequences``/etc. Caller keys win on
        conflict.

    Retries up to 5 times with exponential backoff on:
    - Rate limits (429)
    - API connection errors
    - Internal server errors (500+)

    Does NOT retry on auth errors, bad requests, timeouts,
    or other permanent failures.

    All LLM calls are logged via structlog with model, tokens, cost, and latency.
    """
    if isinstance(system, str):
        # Build up prefix layers: datetime → personality → style → system prompt.
        prefix = ""
        if inject_datetime:
            prefix += _current_datetime_preamble(user_timezone)
        if inject_personality:
            prefix += get_personality_prefix() + get_response_style_prefix()
        if prefix:
            system = prefix + system

    system_blocks = _build_system_blocks(system, cache_system=cache_system)

    _call_start = time.monotonic()
    # GenAI OpenTelemetry span (April 2026 semconv — "Development" status).
    # Span attributes carry request/response metadata; prompt + completion
    # CONTENT is omitted by default. Operators must separately opt in before
    # redacted prompt/completion events are emitted.
    tracer = get_tracer()
    pii_on = _pii_redaction_enabled()
    export_content = _otel_content_export_enabled()
    with tracer.start_as_current_span("gen_ai.client") as span:
        _set_genai_request_attrs(
            span,
            model=model,
            max_tokens=max_tokens,
            output_config=output_config,
            thinking_mode=thinking_mode,
            effort=effort,
        )
        bind_request_id(span, _current_request_id())
        if export_content:
            _emit_genai_prompt_events(
                span,
                system=system_blocks,
                messages=messages,
                redact_pii=pii_on,
            )
        try:
            create_kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system_blocks,
                "messages": messages,
                "timeout": httpx.Timeout(timeout_seconds, connect=10.0),
            }
            if _tools is not None:
                create_kwargs["tools"] = _tools
            # Extended-thinking adaptive-mode kwargs (never emits budget_tokens).
            create_kwargs.update(
                _build_thinking_kwargs(
                    effort=effort,
                    thinking_mode=thinking_mode,
                    output_config=output_config,
                )
            )
            if isinstance(client, BaseLLMProvider):
                response = await client.complete(**create_kwargs)
            else:
                # Compatibility path for existing call sites and test doubles.
                response = await client.messages.create(**create_kwargs)
        except httpx.TimeoutException as e:
            _record_span_exception(span, e)
            raise LLMError(f"LLM call timed out after {timeout_seconds}s") from e
        except anthropic.APITimeoutError as e:
            _record_span_exception(span, e)
            raise LLMError(f"LLM call timed out after {timeout_seconds}s") from e
        except Exception as e:
            _record_span_exception(span, e)
            raise

        # Log every LLM call via structlog (model, tokens, cache, latency).
        # Cache fields are defensive — not every response shape exposes them,
        # and the per-TTL breakdown only appears when the extended-cache-ttl
        # beta is on.
        # 2026-03-06: Anthropic silently flipped the default ephemeral TTL
        # from 1h to 5m — track both so cost spikes are visible.
        duration_ms = int((time.monotonic() - _call_start) * 1000)
        usage = response.usage
        fresh_input = getattr(usage, "input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create_total = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_create_obj = getattr(usage, "cache_creation", None)
        cache_5m = (
            getattr(cache_create_obj, "ephemeral_5m_input_tokens", 0) or 0
            if cache_create_obj is not None
            else 0
        )
        cache_1h = (
            getattr(cache_create_obj, "ephemeral_1h_input_tokens", 0) or 0
            if cache_create_obj is not None
            else 0
        )
        total_input = fresh_input + cache_read + cache_create_total
        cache_hit_rate = round(cache_read / total_input, 4) if total_input else 0.0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cost_usd, cost_gbp = estimate_cost(
            model=model,
            fresh_input_tokens=fresh_input,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_5m_input_tokens=cache_5m,
            cache_creation_1h_input_tokens=cache_1h,
        )

        _set_genai_response_attrs(
            span,
            fresh_input=fresh_input,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_create_total=cache_create_total,
            cache_5m=cache_5m,
            cache_1h=cache_1h,
            cache_hit_rate=cache_hit_rate,
            cost_usd=cost_usd,
            cost_gbp=cost_gbp,
            duration_ms=duration_ms,
        )
        if export_content:
            _emit_genai_completion_event(span, response=response, redact_pii=pii_on)

        logger.info(
            "llm_call_success",
            model=model,
            tokens_in=fresh_input,
            tokens_out=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_create_total,
            cache_creation_ephemeral_5m=cache_5m,
            cache_creation_ephemeral_1h=cache_1h,
            cache_hit_rate=cache_hit_rate,
            cost_usd=cost_usd,
            cost_gbp=cost_gbp,
            price_table_version=price_table_version(),
            duration_ms=duration_ms,
            has_tools=_tools is not None,
        )

        return response


def extract_text(response) -> str:
    """Safely extract text from an Anthropic API response.

    Raises LLMError if response has no text content.
    """
    if not response.content:
        raise LLMError("LLM returned empty response content")
    block = response.content[0]
    if not hasattr(block, "text"):
        raise LLMError(f"LLM returned non-text content block: {block.type}")
    return block.text


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from model output using three fallback strategies.

    Strategy 1 — direct: the whole string is valid JSON (ideal case).
    Strategy 2 — fenced: find ```json...``` or ```...``` anywhere in the text.
    Strategy 3 — greedy: grab the first {...} block in the string.

    Models sometimes prepend a sentence or two before the JSON despite being
    told not to. Strategy 2 + 3 rescue those cases so retries aren't wasted.
    Raises json.JSONDecodeError if all three strategies fail.
    """
    # Strategy 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: find ```json ... ``` or ``` ... ``` block anywhere
    fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", raw)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: grab first { ... } JSON object (handles trailing text too)
    brace_match = re.search(r"\{[\s\S]*\}", raw)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found in model output", raw, 0)


def parse_json_response(response, error_context: str = "LLM") -> dict:
    """Extract text from response and parse as JSON.

    Uses _extract_json which tries three strategies: direct, fenced, greedy.
    Raises LLMError on empty response or invalid JSON.
    """
    raw = extract_text(response).strip()
    try:
        return _extract_json(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"Failed to parse {error_context} response: {raw}") from e


async def call_and_parse(
    client: LLMClient,
    *,
    model: str,
    max_tokens: int,
    system: SystemPrompt,
    messages: list[dict],
    response_model: type[T],
    error_context: str,
    timeout_seconds: float = 120.0,
    inject_personality: bool = True,
    effort: Effort | None = None,
    thinking_mode: ThinkingMode | None = None,
    output_config: dict | None = None,
) -> T:
    """Call LLM and parse response into a Pydantic model.

    Single-shot version — use call_and_parse_with_retry for structured outputs
    where you want automatic correction passes on parse failures.

    Accepts the same ``effort`` / ``thinking_mode`` / ``output_config`` kwargs
    as :func:`call_llm`; passing ``output_config`` is safe (it is merged on
    top of anything derived from ``effort``).
    """
    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            timeout_seconds=timeout_seconds,
            inject_personality=inject_personality,
            effort=effort,
            thinking_mode=thinking_mode,
            output_config=output_config,
        )
    except (anthropic.APIError, LLMError) as e:
        logger.error(
            f"{error_context}_failed",
            error_class=type(e).__name__,
            model=model,
        )
        raise LLMError(f"{error_context} failed: {e}") from e
    try:
        return response_model(**parse_json_response(response, error_context))
    except (ValueError, ValidationError) as e:
        raise LLMError(f"Failed to parse {error_context}: {e}") from e


async def call_and_parse_with_retry(
    client: LLMClient,
    *,
    model: str,
    max_tokens: int,
    system: SystemPrompt,
    messages: list[dict],
    response_model: type[T],
    error_context: str,
    timeout_seconds: float = 120.0,
    inject_personality: bool = True,
    max_attempts: int = _MAX_PARSE_RETRIES,
    effort: Effort | None = None,
    thinking_mode: ThinkingMode | None = None,
    output_config: dict | None = None,
) -> T:
    """Call LLM and parse into a Pydantic model, with retry-with-feedback.

    When the model returns malformed JSON or a schema that fails Pydantic
    validation, this function re-submits the conversation with the model's
    bad output appended as an assistant turn and a correction instruction as
    the next user turn. The model sees exactly what it got wrong and
    self-corrects — typically within 1-2 additional passes.

    Up to ``max_attempts`` total attempts (default 5). Raises LLMError
    after exhausting all attempts so the caller can handle it explicitly.
    """
    current_messages = list(messages)
    last_error: str = ""
    last_raw: str = ""

    for attempt in range(1, max_attempts + 1):
        try:
            response = await call_llm(
                client,
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=current_messages,
                timeout_seconds=timeout_seconds,
                inject_personality=inject_personality,
                effort=effort,
                thinking_mode=thinking_mode,
                output_config=output_config,
            )
        except (anthropic.APIError, LLMError) as e:
            logger.error(
                f"{error_context}_llm_failed",
                attempt=attempt,
                error_class=type(e).__name__,
                model=model,
            )
            raise LLMError(f"{error_context} failed: {e}") from e

        try:
            raw = extract_text(response).strip()
            parsed_dict = _extract_json(raw)
            result = response_model(**parsed_dict)
            if attempt > 1:
                logger.info(
                    f"{error_context}_parse_recovered",
                    attempt=attempt,
                    model=model,
                )
            return result

        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            last_error = str(e)
            last_raw = extract_text(response).strip() if response.content else ""
            logger.warning(
                f"{error_context}_parse_failed_retrying",
                attempt=attempt,
                max_attempts=max_attempts,
                error=last_error,
                model=model,
            )

            if attempt == max_attempts:
                break

            # Feed the bad output back to the model as a correction prompt.
            # The model sees its own malformed response and exactly what's wrong.
            current_messages = [
                *current_messages,
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": (
                        f"That response could not be parsed. Error: {last_error}\n\n"
                        f"Please try again and return ONLY valid JSON matching the "
                        f"required schema. No markdown fences, no explanatory text."
                    ),
                },
            ]

    raise LLMError(
        f"Failed to parse {error_context} after {max_attempts} attempts. Last error: {last_error}"
    )


async def call_and_extract_text(
    client: LLMClient,
    *,
    model: str,
    max_tokens: int,
    system: SystemPrompt,
    messages: list[dict],
    error_context: str,
    timeout_seconds: float = 120.0,
    inject_personality: bool = True,
    effort: Effort | None = None,
    thinking_mode: ThinkingMode | None = None,
    output_config: dict | None = None,
) -> str:
    """Call LLM and extract plain text response.

    Accepts the same ``effort`` / ``thinking_mode`` / ``output_config`` kwargs
    as :func:`call_llm`.
    """
    try:
        response = await call_llm(
            client,
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            timeout_seconds=timeout_seconds,
            inject_personality=inject_personality,
            effort=effort,
            thinking_mode=thinking_mode,
            output_config=output_config,
        )
    except (anthropic.APIError, LLMError) as e:
        logger.error(
            f"{error_context}_failed",
            error_class=type(e).__name__,
            model=model,
        )
        raise LLMError(f"{error_context} failed: {e}") from e
    return extract_text(response)
