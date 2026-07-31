"""Tests for shared LLM response helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

from src.app.core.exceptions import LLMError
from src.app.core.llm_helpers import _extract_json, call_llm, extract_text, parse_json_response


def _make_response(text: str | None = None, empty: bool = False):
    """Build a mock response."""
    response = MagicMock()
    if empty:
        response.content = []
    elif text is not None:
        block = MagicMock()
        block.text = text
        block.type = "text"
        response.content = [block]
    return response


def _make_tool_response():
    """Build a mock response with a tool_use block (no text)."""
    response = MagicMock()
    block = MagicMock(spec=["type", "id", "name", "input"])
    block.type = "tool_use"
    del block.text  # Ensure no .text attribute
    response.content = [block]
    return response


def test_extract_text_success():
    response = _make_response('{"key": "value"}')
    assert extract_text(response) == '{"key": "value"}'


def test_extract_text_empty_content_raises():
    response = _make_response(empty=True)
    with pytest.raises(LLMError, match="empty response content"):
        extract_text(response)


def test_extract_text_non_text_block_raises():
    response = _make_tool_response()
    with pytest.raises(LLMError, match="non-text content block"):
        extract_text(response)


def test_parse_json_response_success():
    response = _make_response('{"name": "test", "value": 42}')
    data = parse_json_response(response, "test")
    assert data == {"name": "test", "value": 42}


def test_parse_json_response_fenced_json():
    """parse_json_response handles ```json...``` anywhere in response."""
    raw = '```json\n{"name": "fenced"}\n```'
    response = _make_response(raw)
    assert parse_json_response(response, "test") == {"name": "fenced"}


def test_parse_json_response_text_then_fenced_json():
    """parse_json_response handles text preamble before a fenced JSON block."""
    raw = 'Here is my answer:\n\n```json\n{"key": "value"}\n```'
    response = _make_response(raw)
    assert parse_json_response(response, "test") == {"key": "value"}


def test_extract_json_direct():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_at_start():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_fenced_with_preamble():
    raw = 'Sure, here you go:\n\n```json\n{"x": 42}\n```'
    assert _extract_json(raw) == {"x": 42}


def test_extract_json_brace_fallback():
    raw = 'Some preamble {"z": 99} and trailing text'
    assert _extract_json(raw) == {"z": 99}


def test_extract_json_no_json_raises():
    import json

    with pytest.raises(json.JSONDecodeError):
        _extract_json("no JSON here at all")


def test_parse_json_response_invalid_json():
    response = _make_response("not json at all")
    with pytest.raises(LLMError, match="Failed to parse test response"):
        parse_json_response(response, "test")


def test_parse_json_response_empty_content():
    response = _make_response(empty=True)
    with pytest.raises(LLMError, match="empty response content"):
        parse_json_response(response, "test")


# ---------------------------------------------------------------------------
# Helper to build a mock Anthropic Message
# ---------------------------------------------------------------------------


def _make_anthropic_message(text: str, input_tokens: int = 50, output_tokens: int = 100):
    """Build a mock that resembles an Anthropic Message response."""
    block = MagicMock()
    block.text = text
    block.type = "text"

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    message = MagicMock()
    message.content = [block]
    message.usage = usage
    return message


# ---------------------------------------------------------------------------
# call_llm — success
# ---------------------------------------------------------------------------


class TestCallLlmSuccess:
    async def test_call_llm_returns_response(self):
        """call_llm should return the API response on success."""
        mock_message = _make_anthropic_message("Hello, world!")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        result = await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="You are helpful.",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert result is mock_message
        client.messages.create.assert_awaited_once()

    async def test_call_llm_passes_system_blocks(self):
        """call_llm should convert plain string system to cached blocks."""
        mock_message = _make_anthropic_message("response")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test system prompt",
            messages=[{"role": "user", "content": "test"}],
            cache_system=True,
            inject_personality=False,
            inject_datetime=False,
        )

        call_kwargs = client.messages.create.call_args
        system_arg = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        # Should be a list with cache_control
        assert isinstance(system_arg, list)
        assert system_arg[0]["type"] == "text"
        assert system_arg[0]["text"] == "Test system prompt"
        assert "cache_control" in system_arg[0]

    async def test_call_llm_no_cache(self):
        """When cache_system=False, system should be passed as plain string."""
        mock_message = _make_anthropic_message("response")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test system prompt",
            messages=[{"role": "user", "content": "test"}],
            cache_system=False,
            inject_personality=False,
            inject_datetime=False,
        )

        call_kwargs = client.messages.create.call_args
        system_arg = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        assert isinstance(system_arg, str)
        assert system_arg == "Test system prompt"


# ---------------------------------------------------------------------------
# call_llm — retry on rate limit
# ---------------------------------------------------------------------------


class TestCallLlmRetryOnRateLimit:
    async def test_retries_on_rate_limit_then_succeeds(self):
        """call_llm should retry on RateLimitError and return on eventual success."""
        mock_message = _make_anthropic_message("Success after retry")
        client = AsyncMock()

        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429, headers={}, json=MagicMock(return_value={})),
            body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
        )

        # Fail twice with rate limit, succeed on third
        client.messages.create = AsyncMock(
            side_effect=[rate_limit_error, rate_limit_error, mock_message]
        )

        result = await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test",
            messages=[{"role": "user", "content": "test"}],
        )

        assert result is mock_message
        assert client.messages.create.await_count == 3

    async def test_retries_on_internal_server_error(self):
        """call_llm should retry on InternalServerError."""
        mock_message = _make_anthropic_message("Success")
        client = AsyncMock()

        internal_error = anthropic.InternalServerError(
            message="Internal server error",
            response=MagicMock(status_code=500, headers={}, json=MagicMock(return_value={})),
            body={"error": {"message": "Internal", "type": "internal_error"}},
        )

        client.messages.create = AsyncMock(side_effect=[internal_error, mock_message])

        result = await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test",
            messages=[{"role": "user", "content": "test"}],
        )

        assert result is mock_message
        assert client.messages.create.await_count == 2

    async def test_exhausts_retries_then_raises(self):
        """After 5 retries, the RateLimitError should propagate."""
        client = AsyncMock()

        rate_limit_error = anthropic.RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429, headers={}, json=MagicMock(return_value={})),
            body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
        )

        client.messages.create = AsyncMock(side_effect=rate_limit_error)

        with pytest.raises(anthropic.RateLimitError):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
            )

        assert client.messages.create.await_count == 5


# ---------------------------------------------------------------------------
# call_llm — permanent (non-retryable) failures
# ---------------------------------------------------------------------------


class TestCallLlmPermanentFailure:
    async def test_auth_error_not_retried(self):
        """AuthenticationError should NOT be retried — fails immediately."""
        client = AsyncMock()

        auth_error = anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401, headers={}, json=MagicMock(return_value={})),
            body={"error": {"message": "Invalid key", "type": "authentication_error"}},
        )

        client.messages.create = AsyncMock(side_effect=auth_error)

        with pytest.raises(anthropic.AuthenticationError):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
            )

        # Should only be called once — no retries
        assert client.messages.create.await_count == 1

    async def test_bad_request_not_retried(self):
        """BadRequestError should NOT be retried — fails immediately."""
        client = AsyncMock()

        bad_request = anthropic.BadRequestError(
            message="Invalid request",
            response=MagicMock(status_code=400, headers={}, json=MagicMock(return_value={})),
            body={"error": {"message": "Bad request", "type": "bad_request_error"}},
        )

        client.messages.create = AsyncMock(side_effect=bad_request)

        with pytest.raises(anthropic.BadRequestError):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
            )

        assert client.messages.create.await_count == 1

    async def test_timeout_raises_llm_error(self):
        """httpx.TimeoutException should be wrapped in LLMError without retry."""
        client = AsyncMock()

        client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

        with pytest.raises(LLMError, match="timed out"):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
                timeout_seconds=30.0,
            )

        assert client.messages.create.await_count == 1

    async def test_api_timeout_raises_llm_error(self):
        """anthropic.APITimeoutError should be wrapped in LLMError without retry."""
        client = AsyncMock()

        timeout_error = anthropic.APITimeoutError(request=MagicMock())

        client.messages.create = AsyncMock(side_effect=timeout_error)

        with pytest.raises(LLMError, match="timed out"):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
            )

        assert client.messages.create.await_count == 1


# ---------------------------------------------------------------------------
# _build_system_blocks
# ---------------------------------------------------------------------------


class TestBuildSystemBlocks:
    """Test _build_system_blocks."""

    def test_list_system_returned_as_is(self):
        from src.app.core.llm_helpers import _build_system_blocks

        blocks = [{"type": "text", "text": "hello"}]
        result = _build_system_blocks(blocks, cache_system=True)
        assert result is blocks

    def test_string_with_cache(self):
        from src.app.core.llm_helpers import _build_system_blocks

        result = _build_system_blocks("hello world", cache_system=True)
        assert isinstance(result, list)
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "hello world"
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_string_without_cache(self):
        from src.app.core.llm_helpers import _build_system_blocks

        result = _build_system_blocks("hello world", cache_system=False)
        assert result == "hello world"


# ---------------------------------------------------------------------------
# call_and_parse
# ---------------------------------------------------------------------------


class TestCallAndParse:
    async def test_success(self):
        """call_and_parse should parse a valid JSON response into the model."""
        from pydantic import BaseModel

        from src.app.core.llm_helpers import call_and_parse

        class TestModel(BaseModel):
            name: str
            value: int

        mock_message = _make_anthropic_message('{"name": "test", "value": 42}')
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        result = await call_and_parse(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test",
            messages=[{"role": "user", "content": "test"}],
            response_model=TestModel,
            error_context="test_parse",
            inject_personality=False,
        )
        assert isinstance(result, TestModel)
        assert result.name == "test"
        assert result.value == 42

    async def test_llm_error_on_api_failure(self):
        """call_and_parse should raise LLMError when the LLM call fails."""
        from pydantic import BaseModel

        from src.app.core.llm_helpers import call_and_parse

        class TestModel(BaseModel):
            name: str

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(LLMError, match="test_parse failed"):
            await call_and_parse(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
                response_model=TestModel,
                error_context="test_parse",
                inject_personality=False,
            )

    async def test_invalid_json_raises_llm_error(self):
        """call_and_parse should raise LLMError on invalid JSON."""
        from pydantic import BaseModel

        from src.app.core.llm_helpers import call_and_parse

        class TestModel(BaseModel):
            name: str

        mock_message = _make_anthropic_message("not json")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        with pytest.raises(LLMError, match="Failed to parse test_parse"):
            await call_and_parse(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
                response_model=TestModel,
                error_context="test_parse",
                inject_personality=False,
            )

    async def test_validation_error_raises_llm_error(self):
        """call_and_parse should raise LLMError on Pydantic validation failure."""
        from pydantic import BaseModel

        from src.app.core.llm_helpers import call_and_parse

        class StrictModel(BaseModel):
            count: int

        # Valid JSON, but wrong types
        mock_message = _make_anthropic_message('{"count": "not_a_number"}')
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        with pytest.raises(LLMError, match="Failed to parse test_validate"):
            await call_and_parse(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
                response_model=StrictModel,
                error_context="test_validate",
                inject_personality=False,
            )


# ---------------------------------------------------------------------------
# call_and_extract_text
# ---------------------------------------------------------------------------


class TestCallAndExtractText:
    async def test_success(self):
        """call_and_extract_text should return plain text."""
        from src.app.core.llm_helpers import call_and_extract_text

        mock_message = _make_anthropic_message("Hello world")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        result = await call_and_extract_text(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test",
            messages=[{"role": "user", "content": "test"}],
            error_context="test_extract",
            inject_personality=False,
        )
        assert result == "Hello world"

    async def test_llm_error_on_api_failure(self):
        """call_and_extract_text should raise LLMError on API failure."""
        from src.app.core.llm_helpers import call_and_extract_text

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(LLMError, match="test_extract failed"):
            await call_and_extract_text(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Test",
                messages=[{"role": "user", "content": "test"}],
                error_context="test_extract",
                inject_personality=False,
            )


# ---------------------------------------------------------------------------
# call_llm — personality injection
# ---------------------------------------------------------------------------


class TestCallLlmPersonalityInjection:
    async def test_call_llm_with_personality_injection(self):
        """call_llm should prepend personality prefix when inject_personality=True."""
        mock_message = _make_anthropic_message("response")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)

        with patch(
            "src.app.core.llm_helpers.get_personality_prefix",
            return_value="<personality>\nTest persona\n</personality>\n\n",
        ):
            await call_llm(
                client,
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system="Base system",
                messages=[{"role": "user", "content": "test"}],
                inject_personality=True,
            )

        call_kwargs = client.messages.create.call_args
        system_arg = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        # Should be a list (cached) with personality prefix + base system
        assert isinstance(system_arg, list)
        assert "<personality>" in system_arg[0]["text"]
        assert "Base system" in system_arg[0]["text"]

    async def test_call_llm_list_system_skips_personality(self):
        """call_llm should not inject personality when system is a list."""
        mock_message = _make_anthropic_message("response")
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=mock_message)
        system_blocks = [{"type": "text", "text": "pre-built blocks"}]

        await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=system_blocks,
            messages=[{"role": "user", "content": "test"}],
            inject_personality=True,
        )

        call_kwargs = client.messages.create.call_args
        system_arg = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        assert system_arg is system_blocks


# ---------------------------------------------------------------------------
# call_llm — API connection error retry
# ---------------------------------------------------------------------------


class TestCallLlmRetryOnAPIConnectionError:
    async def test_retries_on_api_connection_error_then_succeeds(self):
        """call_llm should retry on APIConnectionError."""
        mock_message = _make_anthropic_message("Success")
        client = AsyncMock()

        connection_error = anthropic.APIConnectionError(
            request=MagicMock(),
        )

        client.messages.create = AsyncMock(side_effect=[connection_error, mock_message])

        result = await call_llm(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="Test",
            messages=[{"role": "user", "content": "test"}],
        )

        assert result is mock_message
        assert client.messages.create.await_count == 2
