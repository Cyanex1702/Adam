"""Bounded HTTPS with address pinning, no proxies, cookies or ambient credentials."""

import ipaddress
import socket
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from adam.core.privacy import contains_secret
from adam.security.request import check_authority


class InternetError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (
            len(value) > 2048
            or parsed.scheme != "https"
            or not host
            or parsed.port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or "\\" in value
            or any(ord(char) <= 32 or ord(char) == 127 for char in unquote(value))
            or contains_secret(unquote(value))
        ):
            raise ValueError()
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        raise InternetError("INTERNET.URL_DENIED") from None


def resolve_public(host: str) -> list[str]:
    try:
        addresses = sorted(
            {str(entry[4][0]) for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        )
        if not addresses or any(
            not ipaddress.ip_address(address).is_global
            or ipaddress.ip_address(address).is_multicast
            or (
                isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address)
                and (
                    ipaddress.IPv6Address(address).ipv4_mapped is not None
                    or ipaddress.IPv6Address(address).sixtofour is not None
                    or ipaddress.IPv6Address(address).teredo is not None
                    or ipaddress.ip_address(address) in ipaddress.ip_network("64:ff9b::/96")
                )
            )
            for address in addresses
        ):
            raise InternetError("INTERNET.ADDRESS_DENIED")
        return addresses
    except (OSError, ValueError) as exc:
        if isinstance(exc, InternetError):
            raise
        raise InternetError("INTERNET.DNS_UNAVAILABLE") from None


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    fetched_at: float


class Network:
    def __init__(
        self,
        resolver: Callable[[str], list[str]] = resolve_public,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.resolver, self.transport = resolver, transport

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        redirects: bool = True,
        allowed_origin: str | None = None,
    ) -> Response:
        deadline = time.monotonic() + 20
        for _ in range(4):
            check_authority()
            url = safe_url(url)
            parsed = urlsplit(url)
            if allowed_origin and parsed.netloc != urlsplit(allowed_origin).netloc:
                raise InternetError("INTERNET.ORIGIN_DENIED")
            host = parsed.hostname or ""
            addresses = self.resolver(host)
            # Pin the already-validated address for the TLS connection. SNI and certificate
            # validation retain the original hostname; DNS cannot change between checks/use.
            address = addresses[0]
            pinned = httpx.URL(url).copy_with(host=address)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InternetError("INTERNET.TIMEOUT")
            request_headers = {
                "Host": parsed.netloc,
                "User-Agent": "ADAM/0.14 (explicit owner retrieval)",
                "Accept-Encoding": "identity",
                **(headers or {}),
            }
            try:
                with (
                    httpx.Client(
                        transport=self.transport,
                        trust_env=False,
                        timeout=min(10, remaining),
                        follow_redirects=False,
                    ) as client,
                    client.stream(
                        method,
                        pinned,
                        headers=request_headers,
                        content=body,
                        extensions={"sni_hostname": host.encode("ascii")},
                    ) as reply,
                ):
                    status, response_headers = reply.status_code, dict(reply.headers)
                    if status in {301, 302, 303, 307, 308}:
                        if not redirects or method != "GET":
                            raise InternetError("INTERNET.REDIRECT_DENIED")
                        url = urljoin(url, reply.headers.get("location", ""))
                        continue
                    encoding = reply.headers.get("content-encoding", "identity").lower()
                    if encoding not in {"identity", "gzip", "deflate"}:
                        raise InternetError("INTERNET.ENCODING_DENIED")
                    decoder = (
                        zlib.decompressobj(31 if encoding == "gzip" else 15)
                        if encoding != "identity"
                        else None
                    )
                    chunks = bytearray()
                    received = 0
                    for chunk in reply.iter_raw(chunk_size=8192):
                        check_authority()
                        if time.monotonic() > deadline:
                            raise InternetError("INTERNET.TIMEOUT")
                        received += len(chunk)
                        if received > 1048576:
                            raise InternetError("INTERNET.RESPONSE_TOO_LARGE")
                        if decoder:
                            try:
                                chunk = decoder.decompress(chunk, 1048577 - len(chunks))
                            except zlib.error:
                                raise InternetError("INTERNET.ENCODING_DENIED") from None
                        chunks.extend(chunk)
                        if len(chunks) > 1048576:
                            raise InternetError("INTERNET.RESPONSE_TOO_LARGE")
                    if decoder and (not decoder.eof or decoder.unused_data):
                        raise InternetError("INTERNET.ENCODING_DENIED")
                    return Response(url, status, response_headers, bytes(chunks), time.time())
            except httpx.HTTPError:
                raise InternetError("INTERNET.NETWORK_UNAVAILABLE") from None
        raise InternetError("INTERNET.REDIRECT_LIMIT")
