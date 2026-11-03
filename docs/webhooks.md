# Optional outgoing webhook automation

Journal can send selected task and time-block changes to a workflow service you choose. This is separate from CalDAV: a successful HTTP delivery confirms receipt by your workflow, not a calendar update. Journal needs no public callback endpoint, cloud account, or workflow service for ordinary offline use.

## Configure a workflow

1. Open Settings and find outgoing webhooks.
2. Enter a name, endpoint URL, and signing secret shared with your receiver. Use HTTPS outside a trusted local network. URLs cannot contain credentials, query strings, or fragments.
3. Select the events and either all lists or specific lists. Enable title sharing only if your workflow needs task titles.
4. Enable the endpoint and send a test delivery. Inspect delivery status before connecting it to another service.

Events contain stable IDs and scheduling metadata. Journal text, task descriptions, connection credentials, and signing secrets are excluded. Titles require separate opt-in. A receiver can retain anything it receives, so select only trusted endpoints. The OS credential vault holds the signing secret; an unavailable vault prevents credential configuration or delivery instead of storing plaintext in SQLite.

Disabling or removing an endpoint cancels queued work. Changing its destination, scope, or sharing settings also cancels old queued work. Re-enabling affects future events; canceled deliveries are not a historical replay. A request already accepted by the receiver cannot be recalled. Use manual retry for failed deliveries after fixing the cause, or retry a pending delivery to bring its next attempt forward. Delivered and canceled records cannot be retried. Test events are synthetic and contain no task or journal content.

## Event contract

Each JSON request has this versioned envelope:

```json
{
  "schema_version": 1,
  "id": "stable-event-id",
  "type": "time_block.updated",
  "entity_id": "stable-time-block-id",
  "entity_version": 2,
  "occurred_at": "2026-11-03T10:00:00Z",
  "data": {}
}
```

Supported subscriptions are `time_block.created`, `time_block.updated`, `time_block.deleted`, and `task.completed`. A test uses `webhook.test`. The payload is captured when the local transaction commits, rather than reconstructed from later state. Deletions retain their entity identity and scheduling snapshot.

Time-block `data` contains `id`, `task_id`, `list_id`, `kind`, `timezone`, `start_at`, `end_at`, `start_date`, and `end_date`. Fields for the other interval kind are null. Task-completion `data` contains `id`, `list_id`, `status`, `completed_at`, `due_date`, `deadline_date`, and an explicit `deadline` object. That object is `{ "kind": "none" }`, `{ "kind": "date", "date": "YYYY-MM-DD" }`, or `{ "kind": "timed", "at": "...Z" }`. Both event families add `title` only when the endpoint opts in. Consumers should allow unknown extra fields within schema version 1.

Scope is evaluated against the task's list when the event occurs. Moving tasks between lists does not publish an inventory reconciliation or remove an already mapped downstream resource. A workflow that needs a complete synchronized inventory must implement reconciliation separately; these events alone are not bidirectional task/calendar sync.

Timed blocks use UTC instants with a `Z` suffix and retain their scheduling time-zone metadata. All-day blocks use calendar dates with an exclusive end date. A one-day block starting November 3 ends November 4; it does not represent a midnight UTC duration. Task deadlines retain their explicit none/date/timed distinction. Consumers should use the payload's scheduling fields instead of inferring all-day intent from the clock time.

Delivery is **at least once**. A receiver might commit work before its response is lost, causing another attempt. Deduplicate by envelope `id`; use `(entity type, entity_id)` as the persistent resource key. Compare `entity_version` within that resource and ignore older or equal versions. Keep deletion tombstones so delayed updates cannot resurrect a deleted resource. Sequence numbers can have gaps, and consumers must tolerate out-of-order arrival. Subscriptions begin with future changes, without an initial inventory export.

## Request authentication

Requests include:

- `X-Journal-Event-Id`: the stable envelope ID.
- `X-Journal-Timestamp`: Unix seconds for this attempt.
- `X-Journal-Signature`: `sha256=` followed by a hexadecimal HMAC-SHA256 digest.

Compute the digest with the shared signing secret over the exact bytes:

```text
ASCII(timestamp) + "." + raw_request_body
```

Verify the signature with a constant-time comparison before parsing or applying the event. Check timestamp freshness, then persist the event ID and resource change in one transaction. Each retry keeps the same event identity but gets a fresh attempt timestamp and signature. Redirects are not followed. Authentication is independent of any downstream calendar credentials; the signing secret is not a bearer-token header.

## Run the local example

The standard-library receiver in [`examples/webhooks/local_workflow.py`](../examples/webhooks/local_workflow.py) demonstrates a small local workflow service. It listens only on loopback and needs no package installation. From the repository root:

```bash
read -rsp 'Webhook signing secret: ' JOURNAL_WEBHOOK_SECRET; echo
export JOURNAL_WEBHOOK_SECRET
python3 examples/webhooks/local_workflow.py --database ./workflow.sqlite
```

Configure `http://127.0.0.1:8787/journal` in Settings with the same secret. Create, edit, and delete a time block, then complete a task. Inspect the example database:

```bash
sqlite3 workflow.sqlite 'SELECT entity_id, version, state FROM resources;'
```

The receiver verifies signatures and a five-minute timestamp window, then atomically records each receipt and resource projection in SQLite. Restarting it with the same database preserves deduplication and resource identity. Repeated updates upsert the existing resource; deletion retains a tombstone. Task completion records a separate completed task resource and leaves its work blocks unchanged. Recurring successors have their own task IDs. This is an example completion policy, not a command to delete calendar events.

For n8n or another local workflow engine, implement the same sequence: verify the raw-body HMAC, transact receipt deduplication and version checking, look up the persistent external-resource ID, then update or delete that resource. Store downstream resource mappings durably; an in-memory workflow variable cannot provide restart-safe identity. A downstream API call and a local transaction are not one atomic operation: use the provider's idempotency key or an additional durable work queue when adding real external writes.

The example stores a local projection instead of contacting a real calendar. It is a development demonstration, not a public internet server. Its database contains the opted-in payload and needs the same privacy care as the workflow service's own data.

## Verification

Backend tests use in-memory Journal databases, fake credential stores, and stub HTTP transports. The example's restart test uses a disposable pytest database. Run:

```bash
cd backend
uv run pytest tests/test_webhook_example.py
uv run pytest -k webhook
```

No test requires a cloud service, real signing secret, or a running n8n instance.
