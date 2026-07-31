"""Embedding provider — generates vector embeddings via Ollama.

No fallback. If Ollama is down, it fails loudly.
"""

import json
import logging

import httpx
import structlog
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.app.core.exceptions import EmbeddingError

logger = structlog.get_logger()
_retry_logger = logging.getLogger("embeddings_retry")

_http_retry = retry(
    retry=retry_if_exception_type(
        (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout),
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(_retry_logger, logging.WARNING),
    reraise=True,
)


class OllamaEmbeddings:
    """Generate embeddings using Ollama's local API."""

    def __init__(self, host: str, model: str) -> None:
        self.host = host
        self.model = model
        self._client = httpx.AsyncClient(base_url=host, timeout=30.0)

    @_http_retry
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of 768-dimensional vectors.
        """
        if not texts:
            return []

        results = []
        # Ollama /api/embed supports batching
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()
            results = data["embeddings"]
        except httpx.HTTPError as e:
            logger.error("embedding_failed", error=str(e), model=self.model)
            raise EmbeddingError(f"Ollama embedding failed: {e}") from e
        except KeyError as e:
            logger.error("embedding_response_invalid", error=str(e))
            raise EmbeddingError("Invalid embedding response: missing 'embeddings' key") from e
        except json.JSONDecodeError as e:
            logger.error("embedding_response_not_json", error=str(e))
            raise EmbeddingError(f"Invalid JSON in embedding response: {e}") from e

        logger.info("embeddings_generated", count=len(results), model=self.model)
        return results

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.embed([text])
        return results[0]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
