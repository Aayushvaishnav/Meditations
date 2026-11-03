"""Optional loopback workflow receiver; standard library only."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class AuthenticationError(ValueError):
    pass


def authenticate(body: bytes, timestamp: str, signature: str, secret: str, *, now: float) -> None:
    try:
        issued = int(timestamp)
    except ValueError:
        raise AuthenticationError("Invalid timestamp") from None
    if abs(now - issued) > 300:
        raise AuthenticationError("Expired signature")
    expected = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationError("Invalid signature")


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS received_events (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS resources (
            entity_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
            state TEXT NOT NULL, payload TEXT NOT NULL
        );
    """)


def apply_event(conn: sqlite3.Connection, event: dict) -> str:
    """Persist receipt and mapping together; tombstones reject delayed updates."""
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("Unsupported schema version")
    event_id, kind = event["id"], event["type"]
    if kind not in {"webhook.test", "time_block.created", "time_block.updated",
                    "time_block.deleted", "task.completed"}:
        raise ValueError("Unsupported event type")
    entity_id, version = event["entity_id"], event["entity_version"]
    if (not isinstance(event_id, str) or not isinstance(entity_id, str)
            or type(version) is not int or version < 1 or not isinstance(event["data"], dict)):
        raise ValueError("Invalid event")
    with conn:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO received_events VALUES (?)", (event_id,),
        ).rowcount
        if not inserted:
            return "duplicate"
        if kind == "webhook.test":
            return "test"
        resource_id = f"{kind.split('.')[0]}:{entity_id}"
        previous = conn.execute(
            "SELECT version FROM resources WHERE entity_id = ?", (resource_id,),
        ).fetchone()
        if previous and previous[0] >= version:
            return "stale"
        state = ("deleted" if kind == "time_block.deleted" else
                 "completed" if kind == "task.completed" else "active")
        conn.execute(
            "INSERT INTO resources VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entity_id) DO UPDATE SET version=excluded.version, "
            "state=excluded.state, payload=excluded.payload",
            (resource_id, version, state, json.dumps(event["data"], ensure_ascii=False)),
        )
    return state


def handler(database: Path, secret: str) -> type[BaseHTTPRequestHandler]:
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/journal":
                self.send_error(404)
                return
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                authenticate(body, self.headers.get("X-Journal-Timestamp", ""),
                             self.headers.get("X-Journal-Signature", ""), secret, now=time.time())
            except (AuthenticationError, ValueError):
                self.send_error(401)
                return
            try:
                event = json.loads(body)
                with closing(sqlite3.connect(database)) as conn:
                    result = apply_event(conn, event)
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            response = json.dumps({"result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Receiver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("workflow.sqlite"))
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    secret = os.environ.get("JOURNAL_WEBHOOK_SECRET", "")
    if not secret:
        parser.error("Set JOURNAL_WEBHOOK_SECRET to the endpoint signing secret")
    with closing(sqlite3.connect(args.database)) as conn:
        initialize(conn)
    print(f"Listening on http://127.0.0.1:{args.port}/journal", flush=True)
    HTTPServer(("127.0.0.1", args.port), handler(args.database, secret)).serve_forever()


if __name__ == "__main__":
    main()
