"""Transport policy and authenticated discovery; all HTTP stays in memory."""
import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest

from app.calendar_sync.adapter import AuthenticationError, CalDAVError, ProtocolError
from app.calendar_sync.credentials import Credentials
from app.calendar_sync.transport import normalize_server_url, open_adapter, same_origin


@pytest.fixture
def anyio_backend():
    return "asyncio"


def credentials(auth_type="basic"):
    return Credentials(username="private-user", password="private-password", auth_type=auth_type)


def discovery_response(path):
    if path == "/":
        prop = '<d:current-user-principal><d:href>/principal/</d:href></d:current-user-principal>'
    elif path == "/principal/":
        prop = '<c:calendar-home-set><d:href>/home/</d:href></c:calendar-home-set>'
    else:
        prop = '<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>Personal</d:displayname><c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'
    return httpx.Response(207, text=f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>{path}</d:href><d:propstat><d:prop>{prop}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')


@pytest.mark.anyio
@pytest.mark.parametrize("auth_type", ["basic", "digest"])
async def test_authenticated_adapter_discovery(auth_type):
    requests = []

    def handle(request):
        requests.append(request)
        authorization = request.headers.get("authorization", "")
        if auth_type == "digest" and not authorization:
            return httpx.Response(401, headers={"www-authenticate": 'Digest realm="calendar", nonce="fixed-nonce", qop="auth", algorithm=MD5'})
        if auth_type == "basic":
            expected = base64.b64encode(b"private-user:private-password").decode()
            assert authorization == f"Basic {expected}"
        else:
            assert authorization.startswith("Digest ")
            assert 'username="private-user"' in authorization
            assert 'response="' in authorization
            assert "private-password" not in authorization
        return discovery_response(request.url.path)

    async with open_adapter("https://calendar.example", credentials(auth_type), transport=httpx.MockTransport(handle)) as adapter:
        calendars = await adapter.discover_calendars()
        assert len(calendars) == 1
        assert calendars[0].url == "https://calendar.example/home/"
        assert calendars[0].supports_vevent
        assert not adapter.client.is_closed
    assert adapter.client.is_closed
    assert len(requests) == (4 if auth_type == "digest" else 3)
    assert all(request.method == "PROPFIND" for request in requests)
    assert all(request.headers["content-type"].startswith("application/xml") for request in requests)
    if auth_type == "digest":
        original, retried = requests[:2]
        assert original.content == retried.content
        assert original.headers["depth"] == retried.headers["depth"] == "0"
        assert original.headers["content-type"] == retried.headers["content-type"]


@pytest.mark.anyio
async def test_client_policy(monkeypatch):
    original = httpx.AsyncClient
    options = {}

    def factory(**kwargs):
        options.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    async with open_adapter("https://calendar.example", credentials(), transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": "https://other.example"}))) as adapter:
        with pytest.raises(ProtocolError):
            await adapter.discover_calendars()
    assert options["trust_env"] is False
    assert options["follow_redirects"] is False
    assert options["timeout"] is None
    assert options["verify"] is True
    assert isinstance(options["auth"], httpx.BasicAuth)


@pytest.mark.anyio
@pytest.mark.parametrize("exception", [RuntimeError("body failed"), asyncio.CancelledError()])
async def test_cleanup_on_exception_and_cancellation(exception):
    with pytest.raises(type(exception)):
        async with open_adapter("https://calendar.example", credentials(), transport=httpx.MockTransport(lambda _: httpx.Response(200))) as adapter:
            raise exception
    assert adapter.client.is_closed


@pytest.mark.anyio
async def test_unknown_auth_rejected_before_client_creation(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Client created before validation")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ValueError, match="Unsupported") as error:
        async with open_adapter("https://calendar.example", SimpleNamespace(username="private-user", password="private-password", auth_type="private-password")):
            pytest.fail("yielded")
    assert "private-password" not in str(error.value)


@pytest.mark.parametrize("url", [
    "https://private-user:private-password@example.org/", "https://example.org/?private-password",
    "https://example.org/#private-password", "https://example.org/?", "https://example.org/#",
    "https://example.org/\n", "https://example.org/%0a", "https://example.org/%7f",
    "https://example.org/\\evil", "ftp://example.org", "https:///path", "https://example.org:bad",
    "http://example.org", "http://localhost.example.org", "http://127.0.0.1.example.org", "http://192.168.1.1",
])
def test_unsafe_urls_rejected_without_secret_echo(url):
    with pytest.raises(ValueError) as error:
        normalize_server_url(url)
    assert "private-password" not in str(error.value)
    assert "private-user" not in str(error.value)


@pytest.mark.parametrize("url", ["http://localhost", "http://LOCALHOST:5232/", "http://127.0.0.1:5232/", "http://127.12.3.4/", "http://[::1]:5232/"])
def test_loopback_plaintext_allowed(url):
    assert normalize_server_url(url).startswith("http://")


def test_explicit_remote_plaintext_and_origin():
    assert normalize_server_url("http://example.org", allow_insecure_http=True) == "http://example.org/"
    assert same_origin("https://EXAMPLE.org/a", "https://example.org:443/b")
    assert not same_origin("https://example.org/", "http://example.org/")
    assert not same_origin("https://example.org/", "https://example.org:444/")


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["auth", "transport"])
async def test_errors_do_not_echo_credentials(failure):
    def handle(request):
        if failure == "auth":
            return httpx.Response(401)
        raise httpx.ConnectError("Connection unavailable", request=request)
    async with open_adapter("https://calendar.example", credentials(), transport=httpx.MockTransport(handle)) as adapter:
        with pytest.raises((AuthenticationError, CalDAVError)) as error:
            await adapter.discover_calendars()
    assert "private-user" not in str(error.value)
    assert "private-password" not in str(error.value)
    assert adapter.client.is_closed
