"""Security and extraction tests for the bounded URL fetcher."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Callable
from unittest.mock import patch

import httpx
import pytest

from src.app.core.url_extractor import ExtractedContent, _validate_url, extract_url_content

_PUBLIC_IP = "93.184.216.34"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _dns_answers(*addresses: str) -> list[tuple[object, ...]]:
    answers: list[tuple[object, ...]] = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        socket_address: tuple[object, ...] = (
            (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        )
        answers.append((family, socket.SOCK_STREAM, 6, "", socket_address))
    return answers


def _client_patch(
    handler: Callable[[httpx.Request], httpx.Response],
):
    transport = httpx.MockTransport(handler)
    return patch(
        "src.app.core.url_extractor.httpx.AsyncClient",
        side_effect=lambda **kwargs: _REAL_ASYNC_CLIENT(transport=transport, **kwargs),
    )


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


class TestExtractedContent:
    def test_defaults(self):
        content = ExtractedContent()
        assert content.title == ""
        assert content.text == ""
        assert content.url == ""
        assert content.word_count == 0


class TestExtractUrlContent:
    async def test_extracts_html_using_pinned_ip_and_original_host(self):
        html = """
        <html>
        <head><title>My Article Title</title></head>
        <body>
            <script>alert('evil');</script>
            <style>.hidden { display: none; }</style>
            <p>This is the main content of the article.</p>
        </body>
        </html>
        """

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == _PUBLIC_IP
            assert request.headers["host"] == "example.com"
            assert request.extensions["sni_hostname"] == "example.com"
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
        ):
            result = await extract_url_content("https://example.com/article")

        assert result.title == "My Article Title"
        assert "main content of the article" in result.text
        assert "alert" not in result.text
        assert "display: none" not in result.text
        assert result.url == "https://example.com/article"

    async def test_uses_final_url_as_title_when_no_title_tag(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content="No title here",
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
        ):
            result = await extract_url_content("https://example.com/no-title")

        assert result.title == "https://example.com/no-title"

    async def test_discards_script_with_whitespace_before_end_tag(self):
        html = "<title>Safe</title><p>Keep this</p><script>discard me</script >"

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=html,
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
        ):
            result = await extract_url_content("https://example.com/article")

        assert result.title == "Safe"
        assert "Keep this" in result.text
        assert "discard me" not in result.text

    async def test_public_redirect_to_loopback_is_blocked_before_second_request(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                side_effect=[
                    _dns_answers(_PUBLIC_IP),
                    _dns_answers("127.0.0.1"),
                ],
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="non-public IP"),
        ):
            await extract_url_content("https://example.com")

        assert len(requests) == 1

    async def test_public_redirect_to_cloud_metadata_is_blocked(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data"},
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                side_effect=[
                    _dns_answers(_PUBLIC_IP),
                    _dns_answers("169.254.169.254"),
                ],
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="non-public IP"),
        ):
            await extract_url_content("https://example.com")

    async def test_dns_rebinding_cannot_change_the_connected_address(self):
        requested_hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_hosts.append(request.url.host)
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content="<title>Safe</title>",
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                side_effect=[
                    _dns_answers(_PUBLIC_IP),
                    _dns_answers("127.0.0.1"),
                ],
            ) as resolver,
            _client_patch(handler),
        ):
            await extract_url_content("https://rebind.example")

        assert resolver.call_count == 1
        assert requested_hosts == [_PUBLIC_IP]

    async def test_mixed_public_and_private_dns_answers_fail_closed(self):
        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP, "10.0.0.7"),
            ),
            pytest.raises(ValueError, match="non-public IP"),
        ):
            await extract_url_content("https://mixed.example")

    async def test_streaming_body_is_capped_after_decompression(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=_ChunkStream([b"a" * 600_000, b"b" * 600_000]),
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="maximum size"),
        ):
            await extract_url_content("https://example.com/large")

    async def test_declared_oversized_body_is_rejected_without_reading(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={
                    "content-length": "1000001",
                    "content-type": "text/html",
                },
                content=b"",
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="maximum size"),
        ):
            await extract_url_content("https://example.com/large")

    async def test_non_text_content_type_is_rejected(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                content=b"binary",
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="content type"),
        ):
            await extract_url_content("https://example.com/file")

    async def test_redirect_limit_is_enforced(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "/again"})

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
            pytest.raises(ValueError, match="redirect limit"),
        ):
            await extract_url_content("https://example.com/start")

    async def test_http_errors_are_propagated(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                headers={"content-type": "text/html"},
                content="not found",
            )

        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(_PUBLIC_IP),
            ),
            _client_patch(handler),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await extract_url_content("https://example.com/missing")


class TestValidateUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/file.txt",
            "file:///etc/passwd",
            "gopher://example.com/",
        ],
    )
    def test_rejects_unsupported_schemes(self, url: str):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            _validate_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://user@example.com/",
            "https://user:password@example.com/",
        ],
    )
    def test_rejects_credentials(self, url: str):
        with pytest.raises(ValueError, match="credentials"):
            _validate_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com:444/",
            "http://example.com:8080/",
            "https://example.com:80/",
        ],
    )
    def test_rejects_non_default_ports(self, url: str):
        with pytest.raises(ValueError, match="port"):
            _validate_url(url)

    def test_rejects_missing_hostname(self):
        with pytest.raises(ValueError, match="no hostname"):
            _validate_url("https:///missing-host")

    def test_rejects_unresolvable_hostname(self):
        with (
            patch("src.app.core.url_extractor.socket.getaddrinfo", side_effect=socket.gaierror),
            pytest.raises(ValueError, match="Cannot resolve hostname"),
        ):
            _validate_url("https://does-not-resolve.example")

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "::1",
            "::ffff:127.0.0.1",
        ],
    )
    def test_rejects_non_public_and_mapped_addresses(self, address: str):
        with (
            patch(
                "src.app.core.url_extractor.socket.getaddrinfo",
                return_value=_dns_answers(address),
            ),
            pytest.raises(ValueError, match="non-public IP"),
        ):
            _validate_url("https://blocked.example")
