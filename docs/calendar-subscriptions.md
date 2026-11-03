# Read-only calendar subscriptions

## Decision and current availability

ICS-03 evaluates two separate features. Neither is implemented by this evaluation.

| Direction | Consumer | Recommendation |
|---|---|---|
| External ICS URL → Journal | Journal fetches a publisher's calendar | Candidate for a future opt-in, read-only subscription feature |
| Journal → another calendar client | The other client fetches a Journal feed | Defer until stable addressing and access controls are implemented and verified |

Today, use [file import](calendar-import.md) for a read-only external inventory,
[calendar export](../plan.md#selected-block-icalendar-snapshots-ics-01) for a selected
work-block snapshot, or [outbound CalDAV](calendar-sync.md) for supported ongoing
publication. File imports and downloads do not refresh automatically. Select an
imported destination in Calendar to show its standalone appointments as a
[read-only overlay](calendar-import.md#show-appointments-on-calendar). Recurring series stay in
the source inventory without occurrence expansion. Live CalDAV inbound events
and automatic URL refresh remain future work.

Both subscription directions are one-way. Subscription edits cannot write back
to Journal, alter local tasks, record focus, change scores, or trigger recurring
task clones. A client that copies an event into an editable calendar creates a
separate copy instead of a write-back channel.

## External URL subscriptions

### Ownership and refresh

A future subscription would give Journal an explicit URL to poll. Journal needs
outbound access to the publisher, instead of an inbound listener, public desktop
address, app account, or CalDAV server. Polling would run only while Journal is
running. Sleep, offline operation, publisher outages and refresh intervals can
delay updates. The UI must show last successful refresh separately from the last
attempt, plus stale/error status and a manual refresh action. Pause retains the
last good local snapshot; removal deletes only subscription-owned local data.
Neither action edits the publisher.

A future implementation should keep URL configuration, polling state and
subscription-owned snapshots separate from file-import destinations, tasks,
work blocks and outbound CalDAV links. A URL change is an explicit new source
or confirmed source replacement; it must not silently merge identities from
different publishers. Event matching stays source + UID + original typed
recurrence identity, including TZID and an explicit series-master marker.

Reuse the file import parser's validation and lossless opaque retention, instead
of its merge policy. File import keeps omitted records because a file can be
partial. The proposed subscription contract accepts only a complete-calendar
snapshot endpoint: a successfully fetched, fully validated response atomically
replaces that subscription's active inventory. Omitted identities then disappear
from that inventory only. An empty valid calendar explicitly clears it. HTTP
success alone cannot prove completeness; users must confirm that the supplied
URL represents the whole subscribed calendar. Undocumented rolling/windowed feeds
are outside the initial contract. A retained snapshot represents publisher output,
instead of authority to delete local tasks or outbound mappings.

Retain recurrence masters, exceptions, cancellations, floating times and timezone
context opaquely. Occurrence expansion and Calendar-grid display require separate
work; subscription fetching must not guess those semantics. Embedded alarms,
attachments, SOURCE properties and other referenced URLs remain data instead of
instructions to execute or fetch.

### HTTP and recovery contract

- Use GET only. Persist ETag and Last-Modified validators only with the snapshot
  they validate; conditional requests can avoid unchanged downloads.
- A 304 retains the last good snapshot. A 304 without an existing snapshot
  requires an unconditional fetch instead of manufacturing an empty calendar.
- Parse the entire successful response before committing inventory and validators
  together. Malformed, truncated or unsupported content leaves both unchanged.
- Network failures, authentication failures, 404 and 410 preserve the last good
  inventory with an actionable error. They never imply an empty calendar.
- Serialize refreshes per source and fence late results against pause, removal,
  URL replacement and newer refresh generations. A departed request cannot
  resurrect a removed source or overwrite a newer snapshot.
- Refresh on explicit request and when due on startup/resume. Coalesce missed
  polls into one current fetch instead of replaying every missed interval.
  Honor publisher rate-limit guidance; do not retry continuously while offline.

Journal, as the consuming client, controls its polling schedule. RFC 7986's
`REFRESH-INTERVAL` is a suggested minimum polling interval, instead of a push
mechanism or freshness guarantee. A future implementation needs a documented
user-controlled interval and retry policy before shipping; this evaluation does
not choose an untested numeric default.

### URL privacy and access

The initial implementation should accept explicit HTTPS URLs; loopback HTTP may
be an explicit local testing option. No file URLs, automatic discovery, browser
OAuth, URL userinfo, ambient cookies or environment credentials are proposed.
Redirects require separate destination approval instead of silently forwarding
secrets to a new origin. Explicit private-network sources can remain an opt-in
local-use case; access to internal services must never be inferred from feed
content or redirected destinations.

A private feed URL can contain a bearer secret in its path or query. Treat the
whole URL as a credential: store it through a dedicated OS-vault entry, keep a
credential-free source identity in SQLite, and exclude it from ordinary responses,
logs, exports and frontend query caches. Re-enter it after restoring on another
machine or when the vault entry is absent. Calendar bodies can repeat private
URLs or contain other sensitive content, so retained snapshots and database
backups still require the existing private-content warning. Define history
retention and explicit source cleanup before adding periodic snapshots.

## Publishing a Journal feed

### Exported scope

If implemented later, a feed must have a persistent explicit selection of local
work-block IDs, independent of the transient ICS download selection and CalDAV
opt-ins. Start with no selected blocks. Adding a block or changing Calendar
filters must never broaden that feed automatically.

Reuse ICS-01's field boundary: stable block-derived UIDs, task title as SUMMARY,
UTC timed instants, exclusive-end all-day dates, and the documented cancellation
mapping. Exclude task descriptions, ordinary deadlines, journals, ratings,
credentials, telemetry, imported appointments and task recurrence rules. A feed
is a complete representation of its selected blocks, instead of an implicit
rolling date window. Removing a selection or deleting its block removes it on
the next successful client refresh; whether a client removes its cached copy
requires interoperability checks.

### Address and access controls

The packaged backend's ephemeral loopback port is unsuitable as a subscription
address. Publishing requires a separate explicit stable address, read-only
endpoint and lifecycle design. A loopback feed is reachable only by clients on
the same machine while Journal is running. A phone or a cloud-based calendar
fetcher cannot use that machine's localhost address. LAN/private-network access
would require intentional binding, routing and HTTPS setup managed by the user.
Cloud hosting, public relays, automatic router configuration and a new public
desktop listener are outside the initial design.

Publishing must remain deferred until it provides per-feed high-entropy bearer
tokens, revocation/rotation and a narrow read-only route that grants no access to
the application API. Use HTTPS beyond loopback. Feed links are secrets; account
for access-log leakage and verify each target client's authentication support.
Any separately exposed listener must serve only authorized feed reads instead
of exposing task or Settings routes. GET/HEAD may read the representation;
PUT/PATCH/POST/DELETE must never mutate Journal through it. Disabling a feed or
revoking its token stops future authorized reads but cannot retract downloaded
or cached copies. Existing application CORS settings are not feed authorization.

The receiving client controls refresh timing and may cache stale data while
Journal is closed. Stable UIDs, HTTP validators and refresh hints help identify
updates, but do not guarantee immediate updates, deletion propagation or client
interoperability. CalDAV remains the existing alternative when supported ongoing
publication is needed without hosting a Journal feed.

## Implementation acceptance gates

Future implementation requires dedicated tests and a new backlog item. This
evaluation alone adds no schema, routes, credentials, network worker or UI.

1. URL polling: initial/unchanged/changed/empty snapshots, source isolation,
   conditional 304 handling, malformed/partial responses, validator atomicity,
   authentication failures, missing endpoints and offline restart recovery.
2. Lifecycle: concurrent refreshes, pause/remove/URL-change races, stale results,
   startup/resume catch-up, credential absence and private-URL leakage checks.
3. Calendar semantics: stable typed recurrence identity, moved exceptions,
   cancellations, all-day exclusive ends, DST and opaque unsupported recurrence;
   no task/block/focus/score mutations or remote writes.
4. Publishing, if separately approved: explicit selection, field exclusions,
   stable UIDs, unauthorized reads, token rotation/revocation, read-only methods,
   stable addressing, app shutdown and cached-copy warnings.
5. Real client checks: refresh/update/removal behavior and supported authentication
   in representative calendar clients. Until measured, publish no fixed refresh
   latency or client compatibility claim. Ordinary tests use fake HTTP responses
   and isolated databases instead of real accounts or OS-vault records.

## References

- [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545): calendar values, identities
  and recurrence semantics; the file format alone does not define synchronization.
- [RFC 7986 §5.7](https://www.rfc-editor.org/rfc/rfc7986#section-5.7): suggested
  minimum refresh interval; §7 and §8 discuss polling and URL privacy risks.
- [RFC 9110 §13](https://www.rfc-editor.org/rfc/rfc9110#section-13): HTTP
  conditional requests. These provide cache validation instead of calendar merge
  or deletion rules.

These standards inform the proposed contract; no calendar-client or live-feed
interoperability was performed for this documentation-only evaluation.
