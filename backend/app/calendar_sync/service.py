"""Read-only reconciliation; outbound dispatch belongs to CAL-04/05."""

from dataclasses import dataclass
from typing import Literal

from app.calendar_sync.adapter import CalDAVAdapter


@dataclass(frozen=True)
class LinkSnapshot:
    id: str
    resource_url: str
    etag: str
    local_revision: int


@dataclass(frozen=True)
class Inspection:
    link: LinkSnapshot
    outcome: Literal["unchanged", "changed", "missing"]


async def inspect_links(
    adapter: CalDAVAdapter, calendar_url: str, links: list[LinkSnapshot],
) -> list[Inspection]:
    """Complete the listing before treating any linked resource as missing."""
    resources = await adapter.list_resources(calendar_url)
    versions = {resource.url: resource.etag for resource in resources}
    return [Inspection(link, "missing" if link.resource_url not in versions else
                       "unchanged" if versions[link.resource_url] == link.etag else "changed")
            for link in links]
