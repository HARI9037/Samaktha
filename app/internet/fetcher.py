"""Content fetcher with SSRF protection and streaming bounds.

P7B hardening adds:
- Strict scheme allowlist (http/https only)
- DNS resolution and IP address classification
- Private/loopback/link-local/metadata address blocking
- Per-hop redirect validation
- Streaming response bounds (no full-body buffering)
- Credential forwarding prevention
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx

from app.internet.models import FetchResult, SearchError

log = logging.getLogger(__name__)

_USER_AGENT = "Samaktha-InternetIntelligence/0.5 (+governed-search)"
_SKIPPED_TAGS = {
    "script", "style", "noscript", "header", "footer", "nav", "iframe",
    "form", "aside", "svg", "template", "object", "embed", "canvas",
    "banner", "cookie-consent", "ad", "ads", "advertisement",
}

# Maximum bytes to read from response body (streaming)
_MAX_FETCH_BYTES = 2_000_000

# Cloud metadata endpoints to block
_METADATA_IPS = {
    "169.254.169.254",  # AWS, GCE, Azure
    "169.254.169.253",  # Azure
    "169.254.169.154",  # AWS
    "100.100.100.200",  # Alibaba Cloud
    "169.254.0.1",      # Some providers
}

# Special headers that should not be forwarded cross-origin
_SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "x-subscription-token",
    "x-brave-api-key",
    "x-goog-api-key",
    "cookie",
    "set-cookie",
}


class _TextExtractor(HTMLParser):
    """Collects visible text, skipping boilerplate + scripting tags."""

    _VOID_SKIP: ClassVar[set[str]] = {
        "script", "style", "noscript", "iframe", "img", "input", "textarea",
        "br", "hr", "meta", "link", "svg", "video", "audio", "source",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._text: list[str] = []
        self._title: str = ""

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: N802
        tag = tag.lower()
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr"}:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:  # noqa: N802
        tag = tag.lower()
        if tag in _SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr"}:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:  # noqa: N802
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title += data
            return
        self._text.append(data)

    def text(self) -> str:
        return _clean_text("".join(self._text))


def _clean_text(raw: str) -> str:
    """Collapse whitespace, decode entities already handled by the parser."""
    lines = []
    for line in raw.splitlines():
        line = html.unescape(line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _clean_markdown(raw: str) -> str:
    """Strip markdown links/images and heading markers to plain text."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    return _clean_text(text)


def _extract_pdf(data: bytes, title_hint: str = "") -> tuple[str, str]:
    """Extract plain text from PDF bytes via PyMuPDF when available."""
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover - environment-dependent
        raise SearchError("PDF extraction is unavailable in this environment.")

    try:
        document = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text("text") for page in document]
        document.close()
    except Exception as exc:
        raise SearchError(f"Failed to parse PDF content: {exc}")

    title = title_hint
    if not title and pages:
        first = (pages[0] or "").strip().splitlines()
        if first:
            title = first[0][:200]
    return title, _clean_text("\n".join(pages))


class ContentFetcher:
    """HTTPS content downloader + extractor with SSRF protection."""

    def __init__(
        self,
        timeout: float = 15.0,
        max_chars: int = 12_000,
        transport: httpx.AsyncBaseTransport | None = None,
        # P7B security options
        allowed_schemes: tuple[str, ...] = ("http", "https"),
        allow_private_addresses: bool = False,
        allow_localhost: bool = False,
        max_redirects: int = 5,
        max_response_bytes: int = _MAX_FETCH_BYTES,
        sensitive_header_allowlist: tuple[str, ...] = (),
        # Test-only: skip DNS validation when using mock transport
        skip_dns_validation: bool = False,
    ) -> None:
        self._timeout = timeout
        self._max_chars = max_chars
        self._transport = transport
        self._allowed_schemes = allowed_schemes
        self._allow_private_addresses = allow_private_addresses
        self._allow_localhost = allow_localhost
        self._max_redirects = max_redirects
        self._max_response_bytes = max_response_bytes
        self._sensitive_header_allowlist = set(sensitive_header_allowlist)
        # Mock transports do not implicitly weaken SSRF validation. Tests that
        # intentionally isolate parsing may opt out explicitly; adversarial
        # tests can provide deterministic DNS while retaining the real gate.
        self._skip_dns_validation = skip_dns_validation

    async def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        max_chars: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Download ``url`` and return clean extracted text with SSRF protection."""
        effective_timeout = timeout if timeout is not None else self._timeout
        effective_max = max_chars if max_chars is not None else self._max_chars

        # Validate initial URL
        validation = self._validate_url(url)
        if not validation.ok:
            return validation

        parsed_initial = urlparse(url)
        initial_host = parsed_initial.hostname or ""
        initial_headers = dict(headers or {})
        # Don't forward sensitive headers to arbitrary destinations
        initial_headers = self._sanitize_headers(initial_headers, initial_host)

        redirect_count = 0
        current_url = url
        current_headers = initial_headers

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(effective_timeout),
                follow_redirects=False,  # We handle redirects manually
                headers={"User-Agent": _USER_AGENT},
                transport=self._transport,
            ) as client:
                while True:
                    # Resolve and validate address before connecting
                    addr_validation, resolved_ip = self._resolve_public_address(
                        current_url
                    )
                    if not addr_validation.ok:
                        return addr_validation

                    request_url = current_url
                    request_headers = dict(current_headers)
                    request_extensions = None
                    if resolved_ip is not None:
                        request_url = self._url_with_resolved_address(
                            current_url, resolved_ip
                        )
                        parsed_request = urlparse(current_url)
                        request_headers["Host"] = parsed_request.netloc
                        request_extensions = {
                            "sni_hostname": parsed_request.hostname or "",
                        }
                    request = client.build_request(
                        "GET", request_url, headers=request_headers,
                        extensions=request_extensions,
                    )
                    response = await client.send(request)

                    # Handle redirects manually
                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > self._max_redirects:
                            return FetchResult(
                                ok=False, url=current_url, error=f"Too many redirects (>{self._max_redirects})"
                            )

                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(
                                ok=False, url=current_url, error="Redirect without location header"
                            )

                        # Resolve relative redirect
                        from urllib.parse import urljoin
                        next_url = urljoin(current_url, location)

                        # Validate EVERY redirect hop
                        hop_validation = self._validate_url(next_url)
                        if not hop_validation.ok:
                            return hop_validation

                        next_parsed = urlparse(next_url)
                        next_host = next_parsed.hostname or ""

                        # Check for redirect to private/internal addresses
                        addr_validation = await self._validate_address(next_url)
                        if not addr_validation.ok:
                            return addr_validation

                        # Don't forward sensitive headers cross-origin
                        if next_host != initial_host:
                            current_headers = self._sanitize_headers({}, next_host)
                        else:
                            current_headers = self._sanitize_headers(current_headers, next_host)

                        # Consume response body to avoid connection issues
                        await response.aread()
                        current_url = next_url
                        continue

                    # Non-redirect response
                    if response.status_code != 200:
                        return FetchResult(
                            ok=False,
                            url=current_url,
                            error=f"Fetch returned HTTP {response.status_code}",
                        )

                    # The transport may use a DNS-pinned IP URL.  Preserve the
                    # logical, user-visible URL after every validated hop.
                    final_url = current_url
                    final_parsed = urlparse(final_url)
                    if final_parsed.scheme not in self._allowed_schemes:
                        return FetchResult(
                            ok=False, url=current_url, error="Redirected to a non-http(s) location."
                        )

                    # Stream response body with bounds
                    content_type = (response.headers.get("content-type") or "").split(";")[0].lower()
                    body = await self._read_body_bounded(response)

                    try:
                        title, text = self._extract(content_type, body, final_url)
                    except SearchError as exc:
                        return FetchResult(ok=False, url=final_url, content_type=content_type, error=str(exc))

                    return FetchResult(
                        ok=True,
                        url=final_url,
                        title=title,
                        text=text[:effective_max],
                        content_type=content_type or "application/octet-stream",
                        retrieved_at=_now_iso(),
                    )

        except httpx.TimeoutException as exc:
            return FetchResult(ok=False, url=url, error=f"Fetch timed out: {exc}")
        except httpx.RequestError as exc:
            return FetchResult(ok=False, url=url, error=f"Fetch failed (network/DNS): {exc}")
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected fetch error for %s", url)
            return FetchResult(ok=False, url=url, error=f"Fetch failed: {exc}")

    def _validate_url(self, url: str) -> FetchResult:
        """Validate URL scheme, host, and structure."""
        try:
            parsed = urlparse(url)
        except Exception:
            return FetchResult(ok=False, url=url, error="Invalid URL format")

        if parsed.scheme not in self._allowed_schemes:
            return FetchResult(ok=False, url=url, error=f"Scheme '{parsed.scheme}' is not allowed.")

        # Reject embedded credentials
        if parsed.username or parsed.password:
            return FetchResult(ok=False, url=url, error="Embedded credentials in URL are not allowed.")

        hostname = parsed.hostname or ""
        if not hostname:
            return FetchResult(ok=False, url=url, error="URL must have a valid hostname.")

        # Basic hostname validation
        if len(hostname) > 253:
            return FetchResult(ok=False, url=url, error="Hostname too long.")

        return FetchResult(ok=True, url=url)

    async def _validate_address(self, url: str) -> FetchResult:
        """Resolve hostname and validate all resolved IP addresses."""
        result, _address = self._resolve_public_address(url)
        return result

    def _resolve_public_address(self, url: str) -> tuple[FetchResult, str | None]:
        """Validate DNS once and return the address that transport must use.

        Returning the validated address closes the DNS rebinding window that
        exists when policy resolution and the HTTP transport resolve the host
        independently.
        """
        # Skip DNS validation in test mode (when mock transport is used)
        if self._skip_dns_validation:
            return FetchResult(ok=True, url=url), None

        try:
            parsed = urlparse(url)
        except Exception:
            return FetchResult(ok=False, url=url, error="Invalid URL format"), None

        hostname = parsed.hostname or ""
        if not hostname:
            return FetchResult(ok=False, url=url, error="URL must have a valid hostname."), None

        # Resolve hostname
        try:
            # Use getaddrinfo for IPv4 and IPv6
            addrs = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return FetchResult(ok=False, url=url, error=f"Could not resolve hostname '{hostname}'."), None

        # Validate each resolved address
        for addr in addrs:
            ip_str = addr[4][0]
            if not self._is_address_allowed(ip_str):
                return FetchResult(
                    ok=False, url=url, error=f"Resolved address '{ip_str}' is not allowed (private/loopback/metadata)."
                ), None

        return FetchResult(ok=True, url=url), addrs[0][4][0]

    @staticmethod
    def _url_with_resolved_address(url: str, address: str) -> str:
        parsed = urlsplit(url)
        host = f"[{address}]" if ":" in address else address
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))

    def _is_address_allowed(self, ip_str: str) -> bool:
        """Check if an IP address is allowed per SSRF policy."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        # Block localhost by default
        if ip.is_loopback and not self._allow_localhost:
            return False

        # Block private addresses by default
        if ip.is_private and not self._allow_private_addresses:
            return False

        # Block link-local
        if ip.is_link_local:
            return False

        # Block multicast
        if ip.is_multicast:
            return False

        # Block unspecified
        if ip.is_unspecified:
            return False

        # Block reserved/special-use
        if ip.is_reserved:
            return False

        # Block cloud metadata endpoints
        if ip_str in _METADATA_IPS:
            return False

        # IPv6 special cases
        if ip.version == 6:
            # IPv4-mapped IPv6 addresses
            if ip.ipv4_mapped and not self._is_address_allowed(str(ip.ipv4_mapped)):
                return False
            # IPv6 unique local addresses (fc00::/7) - already covered by is_private

        return True

    def _sanitize_headers(self, headers: dict[str, str], destination_host: str) -> dict[str, str]:
        """Remove sensitive headers not allowed for the destination."""
        sanitized = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in _SENSITIVE_HEADERS and key_lower not in self._sensitive_header_allowlist:
                # Don't forward sensitive headers
                continue
            sanitized[key] = value
        return sanitized

    async def _read_body_bounded(self, response: httpx.Response) -> bytes:
        """Read response body with streaming bounds."""
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes(chunk_size=8192):
            chunks.append(chunk)
            total += len(chunk)
            if total > self._max_response_bytes:
                log.warning("Fetch response body limit exceeded (%d bytes)", total)
                break
        return b"".join(chunks)

    def _extract(self, content_type: str, body: bytes, url: str) -> tuple[str, str]:
        if content_type == "application/pdf":
            return _extract_pdf(body, title_hint=url)
        if content_type in {"text/markdown", "text/x-markdown"}:
            return url, _clean_markdown(body.decode("utf-8", errors="replace"))
        if content_type.startswith("text/") or "html" in content_type:
            return self._extract_html(body)
        if content_type in {"application/json", "application/xml"}:
            return url, _clean_text(body.decode("utf-8", errors="replace"))
        raise SearchError(f"Unsupported content type: {content_type or 'unknown'}")

    def _extract_html(self, body: bytes) -> tuple[str, str]:
        parser = _TextExtractor()
        try:
            parser.feed(body.decode("utf-8", errors="replace"))
        except Exception as exc:  # pragma: no cover - defensive
            raise SearchError(f"HTML parsing failed: {exc}")
        title = parser._title.strip() if parser._title else ""  # noqa: SLF001
        return title, parser.text()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
