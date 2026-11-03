"""Credential-scoped CalDAV clients; no environment authentication or proxies."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from .adapter import CalDAVAdapter

if TYPE_CHECKING:
    from .credentials import Credentials


def normalize_server_url(server_url: str, *, allow_insecure_http: bool = False) -> str:
    """Validate a server URL; remote plaintext requires explicit caller consent."""
    message = "CalDAV server URL must be HTTP(S), without credentials, query, fragment, or controls"
    if not isinstance(server_url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in unquote(server_url)):
        raise ValueError(message)
    try:
        parts = urlsplit(server_url)
        port = parts.port
        host = parts.hostname
        if (parts.scheme not in {"http", "https"} or not host
                or parts.username is not None or parts.password is not None
                or "?" in server_url or "#" in server_url or "\\" in server_url):
            raise ValueError(message)
        loopback = host.lower() == "localhost"
        try:
            loopback = loopback or ip_address(host).is_loopback
        except ValueError:
            pass
        if parts.scheme == "http" and not loopback and not allow_insecure_http:
            raise ValueError("Remote plaintext CalDAV requires explicit permission")
        hostname = host.lower()
        authority = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None:
            authority += f":{port}"
        return urlunsplit((parts.scheme, authority, parts.path or "/", "", ""))
    except ValueError:
        raise ValueError(message) from None


def same_origin(first: str, second: str) -> bool:
    """Compare validated URL origins, including effective default ports."""
    def origin(value: str) -> tuple[str, str | None, int]:
        parts = urlsplit(normalize_server_url(value, allow_insecure_http=True))
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        return parts.scheme, parts.hostname, port

    return origin(first) == origin(second)


@asynccontextmanager
async def open_adapter(
    server_url: str,
    credentials: "Credentials",
    *,
    allow_insecure_http: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[CalDAVAdapter]:
    """Yield an authenticated adapter; close its isolated client on every exit."""
    url = normalize_server_url(server_url, allow_insecure_http=allow_insecure_http)
    auth_classes = {"basic": httpx.BasicAuth, "digest": httpx.DigestAuth}
    if credentials.auth_type not in auth_classes:
        raise ValueError("Unsupported CalDAV authentication type")
    auth = auth_classes[credentials.auth_type](credentials.username, credentials.password)
    async with httpx.AsyncClient(
        auth=auth, trust_env=False, follow_redirects=False, timeout=None,
        verify=True, transport=transport,
    ) as client:
        yield CalDAVAdapter(url, client)
