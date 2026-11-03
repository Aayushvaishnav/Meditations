import asyncio
import httpx
import pytest
from app.calendar_sync.adapter import CalDAVAdapter, CalDAVError, ProtocolError, AuthenticationError, ConflictError, NotFoundError

BASE = 'https://calendar.example/dav/'


def run(handler, operation):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return await operation(CalDAVAdapter(BASE, client))
    return asyncio.run(execute())


def xml(href, props):
    return f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'


def listing(*rows):
    collection = xml('/dav/', '<d:resourcetype><d:collection/></d:resourcetype>')
    return collection.replace('</d:multistatus>', ''.join(row.split('>', 1)[1].rsplit('</d:multistatus>', 1)[0] for row in rows) + '</d:multistatus>')


@pytest.mark.parametrize('document', [
    '<d:multistatus xmlns:d="DAV:"/>',
    xml('a.ics', '<d:resourcetype/><d:getetag>"v1"</d:getetag>'),
    xml('/dav/', '<d:resourcetype/>'),
    listing(xml('/dav/', '<d:resourcetype><d:collection/></d:resourcetype>')),
    listing(xml('a.ics', '<d:resourcetype/><d:getetag>"v1"</d:getetag>'), xml('./a.ics', '<d:resourcetype/><d:getetag>"v2"</d:getetag>')),
    listing(xml('a.ics', '<d:getetag>"v1"</d:getetag>')),
    listing(xml('nested/a.ics', '<d:resourcetype/><d:getetag>"v1"</d:getetag>')),
    listing(xml('/elsewhere/a.ics', '<d:resourcetype/><d:getetag>"v1"</d:getetag>')),
    listing().replace('</d:multistatus>', '<d:error><d:number-of-matches-within-limits/></d:error></d:multistatus>'),
    listing().replace('</d:response>', '<d:error/></d:response>'),
    listing().replace('</d:propstat>', '<d:error/></d:propstat>'),
    listing().replace('</d:multistatus>', '<d:unknown/></d:multistatus>'),
    listing().replace('</d:response>', '<d:unknown/></d:response>'),
    listing().replace('</d:propstat>', '<d:status>HTTP/1.1 507 Partial</d:status></d:propstat>'),
])
def test_incomplete_listing_is_rejected(document):
    with pytest.raises(ProtocolError):
        run(lambda r: httpx.Response(207, text=document), lambda a: a.list_resources(BASE))


def test_valid_empty_collection():
    assert run(lambda r: httpx.Response(207, text=listing()), lambda a: a.list_resources(BASE)) == []


def test_discovery():
    seen = []
    def handler(r):
        seen.append(r.url.path)
        assert r.method == 'PROPFIND'
        assert r.headers['depth'] == ('1' if len(seen) == 3 else '0')
        documents = [xml('/dav/', '<d:current-user-principal><d:href>people/me/</d:href></d:current-user-principal>'), xml('/dav/people/me/', '<c:calendar-home-set><d:href>../../calendars/</d:href></c:calendar-home-set>'), xml('work/', '<d:resourcetype><c:calendar/></d:resourcetype><d:current-user-privilege-set><d:privilege><d:write/></d:privilege></d:current-user-privilege-set><c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>')]
        return httpx.Response(207, text=documents[len(seen)-1])
    result = run(handler, lambda a: a.discover_calendars())
    assert seen == ['/dav/', '/dav/people/me/', '/dav/calendars/']
    assert result[0].url == BASE + 'calendars/work/'
    assert result[0].writable and result[0].supports_vevent


def test_listing_get_and_writes():
    seen = []
    def handler(r):
        seen.append(r)
        if r.method == 'PROPFIND':
            return httpx.Response(207, text=listing(xml('a.ics', '<d:resourcetype/><d:getetag>"v1"</d:getetag>')))
        return httpx.Response(200 if r.method == 'GET' else 204, content=b'bytes\xff', headers={'ETag': '"v1"'})
    async def operation(a):
        listing = await a.list_resources(BASE)
        assert listing[0].payload is None
        result = await a.get_resource(listing[0].url)
        assert result.payload == b'bytes\xff'
        await a.put_resource('a.ics', b'new')
        await a.put_resource('a.ics', b'update', etag='"v1"')
        await a.delete_resource('a.ics', etag='"v1"')
    run(handler, operation)
    assert seen[2].headers['if-none-match'] == '*'
    assert seen[3].headers['if-match'] == '"v1"'
    assert seen[4].headers['if-match'] == '"v1"'


@pytest.mark.parametrize('status,error', [(401, AuthenticationError), (403, AuthenticationError), (404, NotFoundError), (412, ConflictError), (302, ProtocolError), (500, ProtocolError)])
def test_http_errors(status, error):
    calls = []
    def handler(r):
        calls.append(r)
        return httpx.Response(status, headers={'Location': 'https://evil.example/'})
    with pytest.raises(error):
        run(handler, lambda a: a.put_resource('a', b'data'))
    assert len(calls) == 1


@pytest.mark.parametrize('etag', [None, '', 'W/"weak"', '*', 'plain'])
def test_strong_etags(etag):
    with pytest.raises(ProtocolError):
        run(lambda r: httpx.Response(200, headers={} if etag is None else {'etag': etag}), lambda a: a.get_resource('a'))


@pytest.mark.parametrize('url', ['https://evil.example/x', '//evil.example/x', 'http://calendar.example/x', 'https://u:p@calendar.example/x', 'https://calendar.example:444/x'])
def test_cross_origin(url):
    def handler(r):
        pytest.fail('unsafe request sent')
    with pytest.raises(ProtocolError):
        run(handler, lambda a: a.get_resource(url))


@pytest.mark.parametrize('document', ['<!DOCTYPE x [<!ENTITY x "secret">]><x/>', '<x/>', '<broken', xml('//evil.example/x', ''), xml('a', '').replace('200 OK', '500 Failed'), xml('a', '').replace('HTTP/1.1 200 OK', 'invalid'), xml('a', '<d:getetag>W/"weak"</d:getetag>'), '<d:multistatus xmlns:d="DAV:"><d:response><d:href>a</d:href></d:response></d:multistatus>'])
def test_invalid_xml(document):
    with pytest.raises(ProtocolError):
        run(lambda r: httpx.Response(207, text=document), lambda a: a.list_resources(BASE))


def test_uncertain_write_no_retry():
    calls = []
    def handler(r):
        calls.append(r)
        raise httpx.ReadError('lost response')
    with pytest.raises(CalDAVError, match='uncertain'):
        run(handler, lambda a: a.put_resource('a', b'data'))
    assert len(calls) == 1


def test_success_without_etag_no_extra_requests():
    calls = []
    def handler(r):
        calls.append(r)
        return httpx.Response(201)
    with pytest.raises(ProtocolError):
        run(handler, lambda a: a.put_resource('a', b'data'))
    assert len(calls) == 1


@pytest.mark.parametrize('etag', ['', 'W/"weak"', '*', 'plain'])
def test_bad_write_etag_is_rejected_before_request(etag):
    def handler(r):
        pytest.fail('invalid precondition sent')
    with pytest.raises(ProtocolError):
        run(handler, lambda a: a.delete_resource('a', etag=etag))


def test_utf16_dtd_rejected():
    document = '<!DOCTYPE x [<!ENTITY x "secret">]><x/>'.encode('utf-16')
    with pytest.raises(ProtocolError):
        run(lambda r: httpx.Response(207, content=document), lambda a: a.list_resources(BASE))


def test_missing_optional_property_does_not_grant_access():
    documents = [xml('/dav/', '<d:current-user-principal><d:href>principal/</d:href></d:current-user-principal>'), xml('/dav/principal/', '<c:calendar-home-set><d:href>/home/</d:href></c:calendar-home-set>'), xml('/home/work/', '<d:resourcetype><c:calendar/></d:resourcetype>')]
    def handler(r):
        return httpx.Response(207, text=documents.pop(0))
    result = run(handler, lambda a: a.discover_calendars())
    assert not result[0].writable and not result[0].supports_vevent


def test_failed_optional_propstat_is_not_accepted_as_success():
    document = listing(xml('a', '<d:resourcetype/><d:getetag>"v1"</d:getetag>'))
    document = document.replace('</d:response>', '<d:propstat><d:prop><d:displayname/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>')
    result = run(lambda r: httpx.Response(207, text=document), lambda a: a.list_resources(BASE))
    assert result[0].etag == '"v1"'
