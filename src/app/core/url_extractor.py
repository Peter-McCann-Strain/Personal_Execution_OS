"""Bounded, SSRF-resistant URL content extraction."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

_RE_WHITESPACE = re.compile(r"\s+")

_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "text/html",
        "text/plain",
    }
)
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_EXTRACTION_LENGTH = 10_000
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_REDIRECTS = 5
_MAX_URL_LENGTH = 2_048
_USER_AGENT = "PersonalExecutionOS/1.0"


class _ReadableHTMLParser(HTMLParser):
    """Collect readable text while discarding executable and style content."""

    _IGNORED_ELEMENTS = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._IGNORED_ELEMENTS:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_ELEMENTS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth == 0 and tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self.text_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)


def _extract_readable_html(html: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    parser.close()
    title = _RE_WHITESPACE.sub(" ", " ".join(parser.title_parts)).strip()
    text = _RE_WHITESPACE.sub(" ", " ".join(parser.text_parts)).strip()
    return title, text


@dataclass(frozen=True)
class _ValidatedTarget:
    """A URL plus the DNS result that must be used for its connection."""

    url: str
    parsed: SplitResult
    hostname: str
    port: int
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


def _normalize_public_ip(raw_address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Normalize an address and reject every non-global destination.

    IPv4-mapped IPv6 addresses are evaluated as their IPv4 destination so
    ``::ffff:127.0.0.1`` cannot bypass loopback checks.
    """
    address = ipaddress.ip_address(raw_address.split("%", maxsplit=1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_global:
        msg = f"URL resolves to a non-public IP: {address}"
        raise ValueError(msg)
    return address


def _validate_url(url: str) -> _ValidatedTarget:
    """Validate syntax, credentials, port, and every current DNS answer."""
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_LENGTH:
        raise ValueError("URL is empty or exceeds the maximum length")
    if any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise ValueError("URL contains whitespace or control characters")
    if "\\" in url:
        raise ValueError("URL contains an ambiguous path separator")

    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        msg = f"Unsupported URL scheme: {parsed.scheme}"
        raise ValueError(msg)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    try:
        hostname = hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise ValueError("URL hostname is not valid IDNA") from exc
    if not hostname:
        raise ValueError("URL has no hostname")

    expected_port = 80 if scheme == "http" else 443
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc
    if explicit_port is not None and explicit_port != expected_port:
        raise ValueError("URL port is not allowed")
    port = explicit_port or expected_port

    try:
        answers = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        msg = f"Cannot resolve hostname: {hostname}"
        raise ValueError(msg) from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for answer in answers:
        address = _normalize_public_ip(str(answer[4][0]))
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError("URL hostname resolved to no usable addresses")

    canonical_parsed = parsed._replace(scheme=scheme)
    return _ValidatedTarget(
        url=urlunsplit(canonical_parsed),
        parsed=canonical_parsed,
        hostname=hostname,
        port=port,
        addresses=tuple(addresses),
    )


def _connect_url(target: _ValidatedTarget) -> str:
    """Replace the hostname with the validated IP used for the TCP connection."""
    address = target.addresses[0]
    ip_literal = f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)
    default_port = 80 if target.parsed.scheme == "http" else 443
    authority = ip_literal if target.port == default_port else f"{ip_literal}:{target.port}"
    return urlunsplit(target.parsed._replace(netloc=authority, fragment=""))


def _host_header(target: _ValidatedTarget) -> str:
    hostname = target.hostname
    try:
        is_ipv6 = isinstance(ipaddress.ip_address(hostname), ipaddress.IPv6Address)
    except ValueError:
        is_ipv6 = False
    if is_ipv6:
        hostname = f"[{hostname}]"
    default_port = 80 if target.parsed.scheme == "http" else 443
    return hostname if target.port == default_port else f"{hostname}:{target.port}"


async def _read_bounded_response(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise ValueError("Response Content-Length is invalid") from exc
        if declared_length < 0 or declared_length > _MAX_RESPONSE_BYTES:
            raise ValueError("Response exceeds the maximum size")

    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("Response exceeds the maximum size")
    return bytes(body)


async def _fetch_hop(target: _ValidatedTarget) -> tuple[httpx.Response, bytes]:
    """Fetch one validated hop without any second hostname resolution."""
    headers = {
        "Accept": "text/html, application/xhtml+xml, text/plain;q=0.8",
        "Host": _host_header(target),
        "User-Agent": _USER_AGENT,
    }
    extensions = {"sni_hostname": target.hostname}
    timeout = httpx.Timeout(15.0, connect=5.0)

    # A fresh client per hop prevents an IP-keyed TLS connection from being
    # reused for a different redirect hostname/SNI value.
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        request = client.build_request(
            "GET",
            _connect_url(target),
            headers=headers,
            extensions=extensions,
        )
        response = await client.send(request, stream=True, follow_redirects=False)
        try:
            if response.status_code in _REDIRECT_STATUS_CODES:
                return response, b""
            response.raise_for_status()

            media_type = (
                response.headers.get("content-type", "").partition(";")[0].strip().casefold()
            )
            if media_type not in _ALLOWED_CONTENT_TYPES:
                raise ValueError("Response content type is not allowed")
            return response, await _read_bounded_response(response)
        finally:
            await response.aclose()


def _decode_body(response: httpx.Response, body: bytes) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


class ExtractedContent(BaseModel):
    title: str = ""
    text: str = ""
    url: str = ""
    word_count: int = 0


async def extract_url_content(url: str) -> ExtractedContent:
    """Fetch an allowed public URL and extract bounded readable text."""
    logger.info("url_extraction_started", url_length=len(url))
    current_url = url

    for redirect_count in range(_MAX_REDIRECTS + 1):
        target = _validate_url(current_url)
        response, body = await _fetch_hop(target)

        if response.status_code not in _REDIRECT_STATUS_CODES:
            html = _decode_body(response, body)
            break

        location = response.headers.get("location")
        if not location:
            raise ValueError("Redirect response is missing a Location header")
        if redirect_count >= _MAX_REDIRECTS:
            raise ValueError("URL exceeded the redirect limit")
        current_url = urljoin(target.url, location)
    else:  # pragma: no cover - the bounded loop always exits or raises
        raise ValueError("URL exceeded the redirect limit")

    extracted_title, extracted_text = _extract_readable_html(html)
    title = extracted_title or current_url
    text = extracted_text[:_MAX_EXTRACTION_LENGTH]

    return ExtractedContent(
        title=title,
        text=text,
        url=current_url,
        word_count=len(text.split()),
    )
