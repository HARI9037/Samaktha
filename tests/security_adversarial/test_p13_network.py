from __future__ import annotations

import socket

import httpx
import pytest

from app.internet.fetcher import ContentFetcher


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "0.0.0.0", "::1", "10.0.0.1", "172.16.0.1",
        "192.168.0.1", "169.254.169.254", "224.0.0.1", "240.0.0.1",
        "::ffff:127.0.0.1", "fc00::1", "fe80::1",
    ],
)
def test_fetcher_rejects_non_public_addresses(address: str) -> None:
    assert not ContentFetcher()._is_address_allowed(address)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd", "ftp://example.test/x", "gopher://example.test/x",
        "https://user:password@example.test/x", "custom://example.test/x",
    ],
)
async def test_fetcher_rejects_non_http_or_credential_urls(url: str) -> None:
    result = await ContentFetcher().fetch(url)
    assert not result.ok


@pytest.mark.asyncio
async def test_mock_transport_does_not_implicitly_disable_dns_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contacted = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal contacted
        contacted += 1
        return httpx.Response(200, text="must not be contacted")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))
        ],
    )
    result = await ContentFetcher(
        transport=httpx.MockTransport(handler)
    ).fetch("https://public-looking.example/x")
    assert not result.ok
    assert contacted == 0
    assert "not allowed" in (result.error or "")


@pytest.mark.asyncio
async def test_public_redirect_to_private_is_denied_and_strips_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contacted: list[tuple[str, dict[str, str]]] = []

    def resolve(host: str, *_args, **_kwargs):
        address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append((request.headers["host"], dict(request.headers)))
        return httpx.Response(
            302,
            headers={"location": "https://private.example/metadata"},
            request=request,
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    result = await ContentFetcher(
        transport=httpx.MockTransport(handler)
    ).fetch(
        "https://public.example/start",
        headers={"Authorization": "Bearer P13_SENTINEL"},
    )
    assert not result.ok
    assert [host for host, _headers in contacted] == ["public.example"]
    assert all(
        "P13_SENTINEL" not in value
        for _host, headers in contacted
        for value in headers.values()
    )


@pytest.mark.asyncio
async def test_dns_rebinding_uses_the_once_validated_public_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = 0
    contacted: list[tuple[str, str]] = []

    def resolve(*_args, **_kwargs):
        nonlocal resolutions
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    def handler(request: httpx.Request) -> httpx.Response:
        contacted.append((request.url.host, request.headers["host"]))
        return httpx.Response(
            200,
            text="safe",
            headers={"content-type": "text/plain"},
            request=request,
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    result = await ContentFetcher(
        transport=httpx.MockTransport(handler)
    ).fetch("https://public.example/data")

    assert result.ok
    assert resolutions == 1
    assert contacted == [("93.184.216.34", "public.example")]
    assert result.url == "https://public.example/data"
