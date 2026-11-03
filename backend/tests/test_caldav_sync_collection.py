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

@pytest.mark.parametrize('inner', [
    change('/dav/events/a.ics', '"a"') * 2,
    change('/other/a.ics', '"a"'),
    removal('/dav/events/a.ics?q=1'),
    removal('/dav/events/../events/a.ics'),
    removal('/dav/events/%2e/a.ics'),
    removal('/dav/events/a.ics').replace('</d:response>', '<d:status>HTTP/1.1 404 Not Found</d:status></d:response>'),
    change('/dav/events/a.ics', '"a"').replace('</d:response>', '<d:status>HTTP/1.1 404 Not Found</d:status></d:response>'),
    change('/dav/events/a.ics', '"a"').replace('</d:prop>', '</d:prop><d:prop/>'),
    change('/dav/events/a.ics', '"a"').replace('</d:getetag>', '<d:x/></d:getetag>'),
])
def test_report_rejects_ambiguous_or_nonmember_changes(inner):
    with pytest.raises(ProtocolError):
        run(lambda request: httpx.Response(207, content=sync_response(inner, 't')), lambda adapter: adapter.sync_collection(COLLECTION))


@pytest.mark.parametrize('token_xml', ['', '<d:sync-token>bad token</d:sync-token>', '<d:sync-token>t<d:x/></d:sync-token>'])
def test_initial_report_requires_one_scalar_token(token_xml):
    with pytest.raises(ProtocolError):
        run(lambda request: httpx.Response(207, content=sync_response(token_xml)), lambda adapter: adapter.sync_collection(COLLECTION))


def test_report_requests_sync_level_one():
    from xml.etree import ElementTree as ET
    def handler(request):
        assert ET.fromstring(request.content).findtext('{DAV:}sync-level') == '1'
        return httpx.Response(207, content=sync_response('', 't'))
    run(handler, lambda adapter: adapter.sync_collection(COLLECTION))


@pytest.mark.parametrize('body', ['valid-sync-token', '<x:error xmlns:x="other"><x:valid-sync-token/></x:error>', '<d:error xmlns:d="DAV:"><d:description>valid-sync-token</d:description></d:error>'])
def test_token_error_requires_exact_dav_precondition(body):
    with pytest.raises(AuthenticationError):
        run(lambda request: httpx.Response(403, content=body), lambda adapter: adapter.sync_collection(COLLECTION))


def test_get_never_classifies_token_expiry():
    with pytest.raises(AuthenticationError):
        run(lambda request: httpx.Response(403, content='<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>'), lambda adapter: adapter.get_resource(COLLECTION + 'a.ics'))


def capability_row(href, reports, status=200):
    return (f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>{reports}</d:prop>'
            f'<d:status>HTTP/1.1 {status} Result</d:status></d:propstat></d:response>')


def test_capability_uses_exact_collection_not_first_row():
    supported = '<d:supported-report-set><d:supported-report><d:report><d:sync-collection/></d:report></d:supported-report></d:supported-report-set>'
    body = capability_row('/dav/other/', supported) + capability_row('/dav/events/', '<d:supported-report-set/>')
    assert run(lambda request: httpx.Response(207, content=sync_response(body)), lambda adapter: adapter.supports_sync_collection(COLLECTION)) is False


def test_missing_optional_capability_property_allows_listing():
    body = capability_row('/dav/events/', '<d:supported-report-set/>', 404)
    assert run(lambda request: httpx.Response(207, content=sync_response(body)), lambda adapter: adapter.supports_sync_collection(COLLECTION)) is False


@pytest.mark.parametrize('reports', [
    '<d:sync-collection/>',
    '<d:supported-report/>',
    '<d:supported-report><d:report><d:sync-collection/><d:expand-property/></d:report></d:supported-report>',
    '<d:supported-report><d:report><d:sync-collection><d:x/></d:sync-collection></d:report></d:supported-report>',
])
def test_capability_rejects_malformed_report_membership(reports):
    body = capability_row('/dav/events/', f'<d:supported-report-set>{reports}</d:supported-report-set>')
    with pytest.raises(ProtocolError):
        run(lambda request: httpx.Response(207, content=sync_response(body)), lambda adapter: adapter.supports_sync_collection(COLLECTION))


def test_report_accepts_missing_optional_property_but_requires_etag():
    body = change('/dav/events/a.ics', '"a"').replace('</d:response>', '<d:propstat><d:prop><d:displayname/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>')
    result = run(lambda request: httpx.Response(207, content=sync_response(body, 't')), lambda adapter: adapter.sync_collection(COLLECTION))
    assert result.changes[0].etag == '"a"'


@pytest.mark.parametrize('status', [405, 501])
def test_explicit_unsupported_report_has_distinct_error(status):
    from app.calendar_sync.adapter import UnsupportedSyncCollection
    with pytest.raises(UnsupportedSyncCollection):
        run(lambda request: httpx.Response(status), lambda adapter: adapter.sync_collection(COLLECTION))
