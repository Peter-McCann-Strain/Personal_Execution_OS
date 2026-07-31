"""Tests for TavilySearch — web search tool."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.app.agents.tools.web_search import SearchError, TavilySearch


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def tavily() -> TavilySearch:
    svc = TavilySearch(api_key="test-api-key")
    svc._client = AsyncMock(spec=httpx.AsyncClient)
    return svc


# ---------------------------------------------------------------------------
# search — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_happy_path(tavily: TavilySearch):
    tavily._client.post.return_value = _mock_response(
        {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://a.com",
                    "content": "Content 1",
                    "score": 0.95,
                },
                {"title": "Result 2", "url": "https://b.com", "content": "Content 2", "score": 0.8},
            ]
        }
    )

    results = await tavily.search("test query")
    assert len(results) == 2
    assert results[0]["title"] == "Result 1"
    assert results[0]["url"] == "https://a.com"
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_search_sends_correct_params(tavily: TavilySearch):
    tavily._client.post.return_value = _mock_response({"results": []})

    await tavily.search("AI trends", max_results=3, search_depth="basic")

    call_kwargs = tavily._client.post.call_args
    body = call_kwargs.kwargs["json"]
    assert body["api_key"] == "test-api-key"
    assert body["query"] == "AI trends"
    assert body["max_results"] == 3
    assert body["search_depth"] == "basic"
    assert body["include_answer"] is False


# ---------------------------------------------------------------------------
# search — empty results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_empty_results(tavily: TavilySearch):
    tavily._client.post.return_value = _mock_response({"results": []})

    results = await tavily.search("obscure query")
    assert results == []


# ---------------------------------------------------------------------------
# search — API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_http_error(tavily: TavilySearch):
    tavily._client.post.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )

    with pytest.raises(SearchError, match="Tavily search failed"):
        await tavily.search("failing query")


# ---------------------------------------------------------------------------
# extract — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_happy_path(tavily: TavilySearch):
    tavily._client.post.return_value = _mock_response(
        {
            "results": [
                {"url": "https://a.com", "raw_content": "Full page content"},
            ]
        }
    )

    results = await tavily.extract(["https://a.com"])
    assert len(results) == 1
    assert results[0]["url"] == "https://a.com"


# ---------------------------------------------------------------------------
# extract — API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_http_error(tavily: TavilySearch):
    tavily._client.post.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )

    with pytest.raises(SearchError, match="Tavily extract failed"):
        await tavily.extract(["https://fail.com"])


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close(tavily: TavilySearch):
    await tavily.close()
    tavily._client.aclose.assert_called_once()
