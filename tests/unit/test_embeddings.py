"""Tests for embedding provider."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.core.embeddings import EmbeddingError, OllamaEmbeddings


@pytest.mark.asyncio
async def test_embed_empty_list():
    """Embedding empty list should return empty list."""
    provider = OllamaEmbeddings(host="http://localhost:11434", model="test")
    result = await provider.embed([])
    assert result == []
    await provider.close()


# ---------------------------------------------------------------------------
# embed with content — mock httpx
# ---------------------------------------------------------------------------


class TestEmbedWithContent:
    async def test_embed_single_text(self):
        """Embedding a single text should return one vector."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="nomic-embed-text")

        fake_embedding = [[0.1, 0.2, 0.3] * 256]  # 768-dim
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": fake_embedding}
        mock_response.raise_for_status = MagicMock()

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed(["hello world"])

        assert result == fake_embedding
        provider._client.post.assert_awaited_once_with(
            "/api/embed",
            json={"model": "nomic-embed-text", "input": ["hello world"]},
        )

    async def test_embed_multiple_texts(self):
        """Embedding multiple texts should return multiple vectors."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        fake_embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": fake_embeddings}
        mock_response.raise_for_status = MagicMock()

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed(["text1", "text2", "text3"])

        assert len(result) == 3
        assert result == fake_embeddings

    async def test_embed_single_convenience(self):
        """embed_single should return a single vector, not a list of vectors."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        fake_embedding = [0.5] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [fake_embedding]}
        mock_response.raise_for_status = MagicMock()

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        result = await provider.embed_single("hello")

        assert result == fake_embedding
        assert isinstance(result, list)
        assert not isinstance(result[0], list)


# ---------------------------------------------------------------------------
# embed error handling
# ---------------------------------------------------------------------------


class TestEmbedErrorHandling:
    async def test_http_error_raises_embedding_error(self):
        """HTTP errors from Ollama should be wrapped in EmbeddingError."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(EmbeddingError, match="Ollama embedding failed"):
            await provider.embed(["test"])

    async def test_missing_embeddings_key_raises(self):
        """If the response is missing the 'embeddings' key, should raise EmbeddingError."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {"model": "test", "unexpected": True}
        mock_response.raise_for_status = MagicMock()

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(EmbeddingError, match="missing 'embeddings' key"):
            await provider.embed(["test"])

    async def test_json_decode_error_raises_embedding_error(self):
        """If the response body is not valid JSON, should raise EmbeddingError."""
        import json

        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(EmbeddingError, match="Invalid JSON"):
            await provider.embed(["test"])

    async def test_connection_error_wrapped_as_embedding_error(self):
        """ConnectError (subclass of HTTPError) is caught and wrapped as EmbeddingError.

        The inner except httpx.HTTPError block catches ConnectError and wraps it
        in EmbeddingError. Since EmbeddingError is not in the tenacity retry list,
        the retry decorator does not retry — the error propagates immediately.
        """
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(EmbeddingError, match="Ollama embedding failed"):
            await provider.embed(["test"])

        # Only called once — inner except catches before tenacity can retry
        assert provider._client.post.await_count == 1


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestEmbedClose:
    async def test_close_calls_aclose(self):
        """close() should call aclose on the underlying httpx client."""
        provider = OllamaEmbeddings(host="http://localhost:11434", model="test-model")

        provider._client = AsyncMock()
        await provider.close()

        provider._client.aclose.assert_awaited_once()
