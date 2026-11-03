"""Disposable calendar smoke protocol and destination restrictions."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_smoke_sidecar import module


@pytest.mark.parametrize("url", ["http://127.0.0.1:5232/", "http://localhost:5232/", "http://[::1]:5232/"])
def test_loopback_urls(url):
    assert module._local_calendar_url(url.rstrip("/")) == url


@pytest.mark.parametrize("url", [
    "https://example.com/", "http://192.168.1.1/", "file:///tmp/calendar",
    "http://localhost.evil/", "http://journal:password@localhost/",
    "http://localhost/?redirect=remote", "http://localhost/#fragment",
    "http://localhost:invalid/", "http://localhost:0/", "http://localhost\\evil/",
    "http://local\nhost/", "http://0.0.0.0/",
])
def test_nonlocal_or_ambiguous_destination_rejected_before_launch(url):
    with pytest.raises(module.SmokeError, match="loopback"):
        module.smoke(Path("does-not-exist"), calendar_server_url=url)


def run_calendar(request):
    def require(condition, message):
        if not condition:
            raise module.SmokeError(message)
    module._smoke_calendar(request, require, "http://127.0.0.1:5232/")


def test_calendar_discovery_auth_and_draft_cleanup():
    url = "http://127.0.0.1:5232/journal/meditations/"
    request = Mock(side_effect=[{"id": "draft"}, [
        {"url": url, "writable": True, "supports_vevent": True},
    ], {"detail": "Unauthorized"}, None])
    run_calendar(request)
    calls = request.call_args_list
    assert calls[0].args == ("POST", "/api/calendar/connections", 201,
                            {"server_url": "http://127.0.0.1:5232/", "calendar_url": url})
    assert calls[1].args == ("POST", "/api/calendar/connections/draft/discover", 200,
                            {"username": "journal", "password": "journal-test-password", "auth_type": "basic"})
    assert calls[2].args[2] == 401
    assert calls[2].args[3]["password"] != calls[1].args[3]["password"]
    assert calls[3].args == ("DELETE", "/api/calendar/connections/draft", 204)


@pytest.mark.parametrize("calendar", [
    {}, {"url": "http://elsewhere/", "writable": True, "supports_vevent": True},
    {"url": "http://127.0.0.1:5232/journal/meditations/", "writable": False, "supports_vevent": True},
    {"url": "http://127.0.0.1:5232/journal/meditations/", "writable": True, "supports_vevent": False},
])
def test_missing_selected_event_calendar_deletes_draft(calendar):
    request = Mock(side_effect=[{"id": "draft"}, [calendar], None])
    with pytest.raises(module.SmokeError, match="not discovered"):
        run_calendar(request)
    assert request.call_args.args == ("DELETE", "/api/calendar/connections/draft", 204)


def test_authentication_failure_deletes_draft():
    request = Mock(side_effect=[{"id": "draft"}, module.SmokeError("expected 200, got 401"), None])
    with pytest.raises(module.SmokeError, match="got 401"):
        run_calendar(request)
    assert request.call_args.args == ("DELETE", "/api/calendar/connections/draft", 204)
