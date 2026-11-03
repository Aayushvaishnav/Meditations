from __future__ import annotations

import hashlib
import hmac
import importlib.util
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location(
    "local_workflow", Path(__file__).parents[2] / "examples/webhooks/local_workflow.py",
)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def event(version=1, kind="time_block.created", event_id="event-1"):
    return {"schema_version": 1, "id": event_id, "type": kind,
            "entity_id": "block-1", "entity_version": version,
            "occurred_at": "2026-11-03T00:00:00Z",
            "data": {"kind": "all_day", "start_date": "2026-11-03",
                     "end_date": "2026-11-04"}}


def test_signature_authenticates_exact_body():
    body, timestamp, secret = b'{"test":true}', "1000", "example-only"
    signature = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256,
    ).hexdigest()
    workflow.authenticate(body, timestamp, signature, secret, now=1000)
    for invalid_body, invalid_time, invalid_signature, now in [
        (body + b" ", timestamp, signature, 1000),
        (body, "bad", signature, 1000),
        (body, timestamp, signature, 1301),
        (body, timestamp, "sha256=invalid", 1000),
    ]:
        with pytest.raises(workflow.AuthenticationError):
            workflow.authenticate(invalid_body, invalid_time, invalid_signature, secret, now=now)


def test_duplicate_attempts_keep_single_mapping():
    with sqlite3.connect(":memory:") as conn:
        workflow.initialize(conn)
        assert workflow.apply_event(conn, event()) == "active"
        assert workflow.apply_event(conn, event()) == "duplicate"
        assert conn.execute("SELECT count(*) FROM resources").fetchone()[0] == 1


def test_delete_tombstone_rejects_out_of_order_updates_after_restart(tmp_path):
    database = tmp_path / "consumer.sqlite"
    with sqlite3.connect(database) as conn:
        workflow.initialize(conn)
        assert workflow.apply_event(conn, event(3, "time_block.deleted", "delete")) == "deleted"
    with sqlite3.connect(database) as conn:
        assert workflow.apply_event(conn, event(2, "time_block.updated", "old")) == "stale"
        assert workflow.apply_event(conn, event(3, "time_block.deleted", "delete")) == "duplicate"
        assert conn.execute("SELECT state, version FROM resources").fetchone() == ("deleted", 3)


def test_completion_has_separate_identity_and_preserves_blocks():
    with sqlite3.connect(":memory:") as conn:
        workflow.initialize(conn)
        workflow.apply_event(conn, event())
        assert workflow.apply_event(conn, event(1, "task.completed", "done")) == "completed"
        assert conn.execute("SELECT entity_id, state FROM resources ORDER BY entity_id").fetchall() == [
            ("task:block-1", "completed"), ("time_block:block-1", "active"),
        ]


def test_invalid_schema_leaves_no_receipt():
    with sqlite3.connect(":memory:") as conn:
        workflow.initialize(conn)
        invalid = event()
        invalid["schema_version"] = 2
        with pytest.raises(ValueError):
            workflow.apply_event(conn, invalid)
        assert conn.execute("SELECT count(*) FROM received_events").fetchone()[0] == 0
