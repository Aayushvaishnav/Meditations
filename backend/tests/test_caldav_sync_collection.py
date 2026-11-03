"""RFC 6578 sync-collection REPORT protocol behavior with MockTransport."""
import httpx
import pytest
from app.calendar_sync.adapter import (
    CalDAVAdapter, ProtocolError, SyncTokenInvalid, AuthenticationError,
)

BASE = 'https://calendar.example/dav/'
COLLECTION = BASE + 'events/'


def run(handler, operation):
    import asyncio
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await operation(CalDAVAdapter(BASE, client))
    return asyncio.run(execute())


def sync_response(body_inner, token=None):
    token_xml = f'<d:sync-token>{token}</d:sync-token>' if token is not None else ''
    return f'<d:multistatus xmlns:d="DAV:">{token_xml}{body_inner}</d:multistatus>'


def change(href, etag):
    return (f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
            f'<d:getetag>{etag}</d:getetag></d:prop>'
            f'<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')


def removal(href):
    return f'<d:response><d:href>{href}</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response>'


def test_initial_sync_collection_returns_changes_and_token():
    def handler(request):
        assert request.method == 'REPORT'
        assert b'sync-collection' in request.content
        return httpx.Response(207, content=sync_response(
            change('/dav/events/a.ics', '"v1"') + change('/dav/events/b.ics', '"v2"'),
            token='http://example/ns/sync/1'))

    result = run(handler, lambda adapter: adapter.sync_collection(COLLECTION))
    assert result.token == 'http://example/ns/sync/1'
    assert [c.url for c in result.changes] == [BASE + 'events/a.ics', BASE + 'events/b.ics']
    assert all(c.etag is not None for c in result.changes)


def test_incremental_sync_reports_deletions_with_null_etag():
    def handler(request):
        return httpx.Response(207, content=sync_response(removal('/dav/events/a.ics'), token='t2'))

    result = run(handler, lambda adapter: adapter.sync_collection(COLLECTION, token='t1'))
    assert result.changes[0].etag is None


def test_invalid_sync_token_raises_recoverable_error():
    def handler(request):
        return httpx.Response(403, content='<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>')

    with pytest.raises(SyncTokenInvalid):
        run(handler, lambda adapter: adapter.sync_collection(COLLECTION, token='expired'))


def test_forbidden_without_valid_sync_token_body_is_authentication():
    def handler(request):
        return httpx.Response(403, content='<d:error xmlns:d="DAV:"/>')

    with pytest.raises(AuthenticationError):
        run(handler, lambda adapter: adapter.sync_collection(COLLECTION, token='t'))


@pytest.mark.parametrize('body', [
    # incremental responses must carry a new token
    sync_response(change('/dav/events/a.ics', '"v1"'), token=None).replace('<d:sync-token>None</d:sync-token>', ''),
    # empty token text
    '<d:multistatus xmlns:d="DAV:"><d:sync-token>  </d:sync-token></d:multistatus>',
    # duplicate tokens
    '<d:multistatus xmlns:d="DAV:"><d:sync-token>a</d:sync-token><d:sync-token>b</d:sync-token></d:multistatus>',
    # unknown multistatus child
    '<d:multistatus xmlns:d="DAV:"><d:mystery/></d:multistatus>',
    # missing etag
    '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/events/a.ics</d:href>'
    '<d:propstat><d:prop/><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>',
    # weak etag
    sync_response(change('/dav/events/a.ics', 'W/"weak"'), token='t'),
    # duplicate hrefs
    '<d:multistatus xmlns:d="DAV:">' + change('/dav/events/a.ics', '"v1"') + change('/dav/events/a.ics', '"v2"') + '</d:multistatus>',
    # DTD injection
    '<!DOCTYPE d [<!ENTITY x "y">]><d:multistatus xmlns:d="DAV:"/>',
])
def test_malformed_sync_responses_are_rejected(body):
    def handler(request):
        return httpx.Response(207, content=body)

    with pytest.raises((ProtocolError, AuthenticationError)):
        run(handler, lambda adapter: adapter.sync_collection(COLLECTION, token='t' if 'sync-token' not in body or 'None' in body else None))


def test_non_multistatus_sync_response_is_rejected():
    def handler(request):
        return httpx.Response(200, content='<ok/>')

    with pytest.raises(ProtocolError):
        run(handler, lambda adapter: adapter.sync_collection(COLLECTION))


def test_whitespace_token_is_rejected_before_the_request():
    with pytest.raises(ProtocolError):
        run(lambda request: httpx.Response(207), lambda adapter: adapter.sync_collection(COLLECTION, token='bad token'))


def test_supported_report_set_detects_sync_collection():
    reports = ('<d:supported-report-set xmlns:d="DAV:">'
               '<d:supported-report><d:report><d:sync-collection/></d:report></d:supported-report>'
               '</d:supported-report-set>')

    def handler(request):
        return httpx.Response(207, content=(
            '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/events/</d:href>'
            f'<d:propstat><d:prop>{reports}</d:prop>'
            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'))

    assert run(handler, lambda adapter: adapter.supports_sync_collection(COLLECTION)) is True


def test_supported_report_set_without_sync_collection():
    def handler(request):
        return httpx.Response(207, content=(
            '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/events/</d:href>'
            '<d:propstat><d:prop><d:supported-report-set>'
            '<d:supported-report><d:report><d:expand-property/></d:report></d:supported-report>'
            '</d:supported-report-set></d:prop>'
            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'))

    assert run(handler, lambda adapter: adapter.supports_sync_collection(COLLECTION)) is False
