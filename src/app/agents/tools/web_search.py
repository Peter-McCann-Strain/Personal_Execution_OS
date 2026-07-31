"""Web search tool — uses Tavily API for research.

Requires TAVILY_API_KEY in env. No fallback.
"""

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

from src.app.core.exceptions import SearchError

logger = structlog.get_logger()
_retry_logger = logging.getLogger("tavily_retry")

_http_retry = retry(
    retry=retry_if_exception_type(
        (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout),
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(_retry_logger, logging.WARNING),
    reraise=True,
)


class TavilySearch:
    """Tavily web search client."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    @_http_retry
    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "advanced",
    ) -> list[dict]:
        """Search the web using Tavily.

        Returns list of: {title, url, content, score}
        """
        try:
            response = await self._client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": search_depth,
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            logger.error(
                "tavily_search_failed",
                error_class=type(e).__name__,
                query_length=len(query),
            )
            raise SearchError(f"Tavily search failed: {e}") from e

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            }
            for r in data.get("results", [])
        ]

        logger.info(
            "tavily_search_completed",
            query_length=len(query),
            results=len(results),
        )
        return results

    @_http_retry
    async def extract(self, urls: list[str]) -> list[dict]:
        """Extract content from URLs using Tavily."""
        try:
            response = await self._client.post(
                "https://api.tavily.com/extract",
                json={
                    "api_key": self.api_key,
                    "urls": urls,
                },
            )
            response.raise_for_status()
            return response.json().get("results", [])
        except httpx.HTTPError as e:
            logger.error("tavily_extract_failed", error=str(e))
            raise SearchError(f"Tavily extract failed: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
