# Import calendar files

Use **Settings → Import calendar files** to keep a read-only copy of appointments
from a UTF-8 iCalendar (`.ics`) file. This is a local file import instead of a
subscription or synchronization connection. No account or server is required.

## Import and inspect

1. Choose **New imported calendar** and give it a name, or choose an existing
   import destination.
2. Choose an `.ics` file, then select **Import .ics file**.
3. Expand **Stored appointments and series** to inspect the saved inventory.

The inventory shows source values, rather than converting them to your device's
timezone. `date` means a calendar date, `utc` means an instant ending in `Z`,
`local` means a value with a source timezone, and `floating` means a wall-clock
value without a timezone. All-day end dates are exclusive.

Recurring series, moved exceptions, canceled occurrences, timezone definitions,
and original recurrence rules are retained. This step preserves them as
read-only calendar content; it does not expand occurrences onto the Calendar
view, schedule reminders, send invitations, or execute alarms. Ordinary imported
appointments can also appear in the read-only overlay described below.

Imports never create tasks or work blocks, complete tasks, record focus, affect
scores, or opt anything into CalDAV publication.

## Show appointments on Calendar

1. Open Calendar and find **Imported calendar** above the grid.
2. Choose an imported destination. **Hidden** removes the overlay.
3. Select an **Imported** appointment to inspect its interval in the day dialog.

One destination is shown at a time. Selection lasts while Calendar remains open,
including month navigation, and resets to Hidden after leaving it. Task list,
search and status filters apply to local plans; the imported overlay stays
independent. Dashed outlines and calendar icons distinguish imported appointments
from task deadlines and work blocks. They cannot be dragged, completed or edited.
A day's **more** control opens all appointments when the grid is crowded.

All-day end dates are exclusive. Zoned appointments display in your device's
local time. Floating appointments retain the file's clock labels without a
timezone conversion. Appointments without a timed end are points on their start
day; date-only appointments without an end occupy one day.

**Outside the grid** lists retained content that cannot be placed safely:
recurring series and exceptions, cancellations, duration-based events, missing
starts, unknown timezones, DST gaps/ambiguities, and invalid intervals. Series
are preserved instead of expanded. The Settings inventory still shows all stored
records. Alarms and attachment URLs remain inactive.

The overlay is a file snapshot. Reimport into the same destination to refresh it;
there is no automatic polling or live CalDAV fetching.

## Reimport policy

- Choose the **same destination** to update its existing appointments. Matching
  uses the event UID and original typed recurrence identity, including its
  timezone. A moved exception keeps the identity of its original occurrence.
- The latest explicit import wins for each matching identity. An older file can
  replace newer imported content; sequence numbers and timestamps do not select
  a winner automatically.
- Identities omitted from the new file remain stored. Importing a partial file
  never implies deletion. Cancellation records remain stored as records.
- A **new destination** creates an independent copy, even if another destination
  contains the same UIDs. Filenames and calendar names do not determine identity.
- Duplicate identities within one file reject the entire import. Unsupported
  components, malformed framing, and detected invalid values also reject the
  entire file, leaving the destination unchanged. Files containing tasks
  (`VTODO`), journals (`VJOURNAL`), or free/busy components need an event-only
  export instead.

Floating times, range overrides, custom properties, attachments and recurrence
semantics that Journal does not interpret remain in the original content. Their
retention does not imply support for scheduling or executing them. Remote URLs
in the file are never fetched.

## Remove and recover

**Remove imported calendar** asks for confirmation, then removes that destination,
its inventory, and its retained upload history. It leaves original files, remote
calendars, local tasks and work blocks unchanged.

Database backups and offline restore include imported calendars and upload
history. Portable ZIP exports exclude this external calendar content. Imported
files can contain private descriptions, attendees, URLs, or embedded attachment
data; treat database backups accordingly. Upload history is retained until the
whole imported calendar is removed.

## Local API

All paths below are under `/api/calendar/imports`:

| Method and path | Behavior |
|---|---|
| `GET /` | List import destinations with IDs, names and inventory counts |
| `POST /` | Atomically import `content` into an explicit `target` |
| `GET /{source_id}/overlay` | Read standalone intervals and explicit unplaced reasons |
| `GET /{source_id}/events` | Read the opaque event inventory |
| `GET /{source_id}/snapshots` | Read original uploaded text and import timestamps |
| `DELETE /{source_id}` | Remove a destination and its retained content |

Routes use the prefix without a trailing slash, for example
`GET /api/calendar/imports`. A new import uses:

```json
{
  "target": { "kind": "new", "name": "Personal appointments" },
  "content": "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
}
```

For a repeat import use `{"kind":"existing","source_id":"SOURCE_ID"}` as the
target. Responses report `source_id` and the numbers `created`, `updated`, and
`unchanged`. A missing source returns 404; rejected calendar data returns 422.
The inventory is read-only, without task ownership or an outbound resource link.
