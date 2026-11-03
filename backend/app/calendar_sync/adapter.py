"""CalDAV wire operations; callers own credentials, selection, and reconciliation."""
from dataclasses import dataclass
import re
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx

DAV = "DAV:"
CAL = "urn:ietf:params:xml:ns:caldav"


class CalDAVError(Exception):
    """Base error; transport failures leave write outcomes uncertain."""


class ProtocolError(CalDAVError):
    pass


class AuthenticationError(CalDAVError):
    pass


class ConflictError(CalDAVError):
    pass


class NotFoundError(CalDAVError):
    pass


@dataclass(frozen=True)
class Calendar:
    url: str
    display_name: str
    writable: bool
    supports_vevent: bool


@dataclass(frozen=True)
class RemoteResource:
    url: str
    etag: str
    payload: bytes | None = None  # None means metadata-only listing


def _strong_etag(value: str | None) -> str:
    if value is None or not re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', value):
        raise ProtocolError("A strong quoted ETag is required")
    return value


def _status(text: str | None) -> int:
    match = re.fullmatch(r"HTTP/\d(?:\.\d)? (\d{3})(?: .*)?", text or "")
    if not match:
        raise ProtocolError("Invalid DAV status")
    return int(match[1])


class CalDAVAdapter:
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self.client = client
        self.base_url = base_url
        self._url(base_url)

    def _url(self, href: str, relative_to: str | None = None) -> str:
        url = urljoin(relative_to or self.base_url, href)
        base, target = urlsplit(self.base_url), urlsplit(url)
        def origin(parts):
            return (parts.scheme.lower(), parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        if (target.scheme not in ("http", "https") or not target.hostname
                or target.username is not None or target.password is not None
                or target.fragment or origin(base) != origin(target)):
            raise ProtocolError("CalDAV URLs must be same-origin HTTP(S) URLs without credentials or fragments")
        return url

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = await self.client.request(method, self._url(url), follow_redirects=False, **kwargs)
        except httpx.TransportError as exc:
            raise CalDAVError("CalDAV transport failure; write outcome may be uncertain") from exc
        if response.status_code in (401, 403):
            raise AuthenticationError("CalDAV authentication or permission denied")
        if response.status_code == 404:
            raise NotFoundError("CalDAV resource not found")
        if response.status_code == 412:
            raise ConflictError("CalDAV precondition failed")
        return response

    async def _properties(self, url: str, depth: int, names: list[tuple[str, str]]):
        url = self._url(url)
        root = ET.Element(f"{{{DAV}}}propfind")
        prop = ET.SubElement(root, f"{{{DAV}}}prop")
        for namespace, name in names:
            ET.SubElement(prop, f"{{{namespace}}}{name}")
        response = await self._request("PROPFIND", url, content=ET.tostring(root), headers={"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"})
        if response.status_code != 207:
            raise ProtocolError(f"Expected DAV multistatus, received {response.status_code}")
        # Reject UTF-16 NULs and DTD/entity syntax before parsing raw XML
        try:
            raw = response.content
            if b"\x00" in raw or re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
                raise ProtocolError("DTD and entity declarations are forbidden")
            tree = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ProtocolError("Malformed DAV XML") from exc
        if tree.tag != f"{{{DAV}}}multistatus":
            raise ProtocolError("Expected DAV multistatus root")
        if any(element.tag in {f"{{{DAV}}}error", f"{{{DAV}}}number-of-matches-within-limits"} for element in tree.iter()):
            raise ProtocolError("DAV listing contains an error or partial-result indicator")
        results = []
        seen_urls = set()
        for item in tree:
            if item.tag == f"{{{DAV}}}responsedescription":
                continue
            if item.tag != f"{{{DAV}}}response":
                raise ProtocolError("Unexpected DAV multistatus child")
            if any(child.tag not in {f"{{{DAV}}}{name}" for name in ("href", "propstat", "status", "responsedescription")} for child in item):
                raise ProtocolError("Unexpected DAV response child")
            hrefs = item.findall(f"{{{DAV}}}href")
            if len(hrefs) != 1 or not hrefs[0].text:
                raise ProtocolError("DAV response requires one href")
            resource_url = self._url(hrefs[0].text, url)
            if resource_url in seen_urls:
                raise ProtocolError("Duplicate DAV resource URL")
            seen_urls.add(resource_url)
            status = item.find(f"{{{DAV}}}status")
            if status is not None:
                raise ProtocolError(f"DAV resource status {_status(status.text)}")
            props = {}
            propstats = item.findall(f"{{{DAV}}}propstat")
            if not propstats:
                raise ProtocolError("Missing DAV propstat")
            seen_properties = set()
            for part in propstats:
                if (len(part.findall(f"{{{DAV}}}status")) != 1
                        or len(part.findall(f"{{{DAV}}}prop")) != 1
                        or any(child.tag not in {f"{{{DAV}}}{name}" for name in ("prop", "status", "responsedescription")} for child in part)):
                    raise ProtocolError("Invalid DAV propstat children")
                code = _status(part.findtext(f"{{{DAV}}}status"))
                values = part.find(f"{{{DAV}}}prop")
                if values is None:
                    raise ProtocolError("Missing DAV prop")
                for value in values:
                    if value.tag in seen_properties:
                        raise ProtocolError("Duplicate or contradictory DAV property")
                    seen_properties.add(value.tag)
                if code == 404:
                    continue
                if code != 200:
                    raise ProtocolError(f"DAV property status {code}")
                for value in values:
                    if value.tag in props:
                        raise ProtocolError("Duplicate DAV property")
                    props[value.tag] = value
            results.append((resource_url, props))
        return results

    async def discover_calendars(self) -> list[Calendar]:
        async def href_property(url, namespace, name):
            rows = await self._properties(url, 0, [(namespace, name)])
            matches = [props[f"{{{namespace}}}{name}"] for resource, props in rows if resource == self._url(url) and f"{{{namespace}}}{name}" in props]
            if len(matches) != 1:
                raise ProtocolError(f"Missing or ambiguous {name}")
            href = matches[0].findtext(f"{{{DAV}}}href")
            if not href:
                raise ProtocolError(f"Missing {name} href")
            return self._url(href, url)
        principal = await href_property(self.base_url, DAV, "current-user-principal")
        home = await href_property(principal, CAL, "calendar-home-set")
        rows = await self._properties(home, 1, [(DAV, "resourcetype"), (DAV, "displayname"), (DAV, "current-user-privilege-set"), (CAL, "supported-calendar-component-set")])
        calendars = []
        for url, props in rows:
            kind = props.get(f"{{{DAV}}}resourcetype")
            if kind is None or kind.find(f"{{{CAL}}}calendar") is None:
                continue
            privileges = props.get(f"{{{DAV}}}current-user-privilege-set", ET.Element("empty"))
            granted = {child.tag for privilege in privileges.findall(f"{{{DAV}}}privilege") for child in privilege}
            writable = f"{{{DAV}}}all" in granted or f"{{{DAV}}}write" in granted or {f"{{{DAV}}}{p}" for p in ("write-content", "bind", "unbind")} <= granted
            components = props.get(f"{{{CAL}}}supported-calendar-component-set", ET.Element("empty"))
            supports = any(c.get("name") == "VEVENT" for c in components.findall(f"{{{CAL}}}comp"))
            name = props.get(f"{{{DAV}}}displayname")
            calendars.append(Calendar(url, name.text or "" if name is not None else "", writable, supports))
        return calendars

    async def list_resources(self, calendar_url: str) -> list[RemoteResource]:
        rows = await self._properties(calendar_url, 1, [(DAV, "resourcetype"), (DAV, "getetag")])
        collection_url = self._url(calendar_url)
        collection_rows = [props for url, props in rows if url == collection_url]
        if len(collection_rows) != 1:
            raise ProtocolError("Listing requires exactly one requested collection response")
        collection_kind = collection_rows[0].get(f"{{{DAV}}}resourcetype")
        if collection_kind is None or collection_kind.find(f"{{{DAV}}}collection") is None:
            raise ProtocolError("Requested resource is not a DAV collection")
        parent_path = unquote(urlsplit(collection_url).path).rstrip("/") + "/"
        resources = []
        for url, props in rows:
            if url == collection_url:
                continue
            target = urlsplit(url)
            path = unquote(target.path)
            member = path[len(parent_path):] if path.startswith(parent_path) else ""
            if target.query or not member.rstrip("/") or "/" in member.rstrip("/") or member.rstrip("/") in (".", ".."):
                raise ProtocolError("DAV response is not an immediate collection member")
            kind = props.get(f"{{{DAV}}}resourcetype")
            if kind is None:
                raise ProtocolError("Missing DAV resource type")
            if kind.find(f"{{{DAV}}}collection") is not None:
                continue
            etag = props.get(f"{{{DAV}}}getetag")
            resources.append(RemoteResource(url, _strong_etag(etag.text if etag is not None else None)))
        return resources

    async def get_resource(self, url: str) -> RemoteResource:
        response = await self._request("GET", url)
        if response.status_code != 200:
            raise ProtocolError(f"Unexpected GET status {response.status_code}")
        return RemoteResource(str(response.request.url), _strong_etag(response.headers.get("etag")), response.content)

    async def put_resource(self, url: str, payload: bytes, *, etag: str | None = None) -> RemoteResource:
        """Create if etag is None; otherwise update only the supplied strong version."""
        if not isinstance(payload, bytes):
            raise TypeError("Calendar payload must be bytes")
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        headers.update({"If-None-Match": "*"} if etag is None else {"If-Match": _strong_etag(etag)})
        response = await self._request("PUT", url, content=payload, headers=headers)
        if response.status_code not in (200, 201, 204):
            raise ProtocolError(f"Unexpected PUT status {response.status_code}; outcome may be uncertain")
        return RemoteResource(str(response.request.url), _strong_etag(response.headers.get("etag")), payload)

    async def delete_resource(self, url: str, *, etag: str) -> None:
        response = await self._request("DELETE", url, headers={"If-Match": _strong_etag(etag)})
        if response.status_code not in (200, 204):
            raise ProtocolError(f"Unexpected DELETE status {response.status_code}; outcome may be uncertain")
