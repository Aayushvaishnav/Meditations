#!/usr/bin/env python3
"""Exercise a frozen backend in an ephemeral, offline sandbox; stdlib only."""
from __future__ import annotations

import argparse
import json
import ipaddress
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class SmokeError(RuntimeError):
    pass


def _local_calendar_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        local = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        if (not local or parsed.scheme not in {"http", "https"}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.port == 0
                or any(ord(char) <= 32 or ord(char) == 127 for char in value)
                or "\\" in value):
            raise ValueError
    except ValueError as error:
        raise SmokeError("calendar server URL must be an HTTP(S) loopback URL without credentials, query, or fragment") from error
    return value.rstrip("/") + "/"


def _smoke_calendar(request, require, server_url: str) -> None:
    calendar_url = server_url + "journal/meditations/"
    draft = request("POST", "/api/calendar/connections", 201,
                    {"server_url": server_url, "calendar_url": calendar_url})
    path = "/api/calendar/connections/" + draft["id"]
    try:
        auth = {"username": "journal", "password": "journal-test-password", "auth_type": "basic"}
        calendars = request("POST", path + "/discover", 200, auth)
        require(any(calendar.get("url") == calendar_url
                    and calendar.get("writable") is True
                    and calendar.get("supports_vevent") is True for calendar in calendars),
                "selected writable VEVENT calendar was not discovered")
        request("POST", path + "/discover", 401, {**auth, "password": "invalid-test-password"})
    finally:
        request("DELETE", path, 204)



def _smoke_calendar_import(request, require) -> None:
    content = ('\ufeffBEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n'
               'UID:packaged-import\r\nDTSTART;TZID=America/New_York:20260101T120000\r\n'
               'RRULE:FREQ=DAILY;COUNT=1000000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
    result = request('POST', '/api/calendar/imports', 200,
                     {'target': {'kind': 'new', 'name': 'Packaged import'}, 'content': content})
    path = '/api/calendar/imports/' + result['source_id']
    try:
        require(result['created'] == 1, 'opaque calendar import did not create one component')
        events = request('GET', path + '/events', 200)
        require(len(events) == 1 and events[0]['start_kind'] == 'local'
                and events[0]['time_zone'] == 'America/New_York'
                and events[0]['representation'] == 'opaque', 'opaque calendar inventory mismatch')
        snapshots = request('GET', path + '/snapshots', 200)
        require(len(snapshots) == 1 and snapshots[0]['content'] == content,
                'original calendar snapshot mismatch')
    finally:
        request('DELETE', path, 204)

def _smoke_restore(binary: Path, backup: Path, target: Path, env: dict[str, str],
                   list_id: str, task_id: str) -> None:
    result = subprocess.run(
        [str(binary), "restore", str(backup), "--database", str(target)],
        cwd=backup.parent, env={**env, "JOURNAL_DB_PATH": str(target)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
    )
    if result.returncode != 0:
        raise SmokeError(f"offline restore failed (exit {result.returncode}):\n{result.stdout}")
    if not target.is_file():
        raise SmokeError("offline restore did not create the target database")
    with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SmokeError("restored database failed integrity check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise SmokeError("restored database failed foreign key check")
        row = connection.execute(
            "SELECT tasks.title, lists.name FROM tasks JOIN lists ON tasks.list_id = lists.id "
            "WHERE tasks.id = ? AND lists.id = ?", (task_id, list_id),
        ).fetchone()
        if row != ("Recovery task", "Recovery list"):
            raise SmokeError("restored database is missing the linked source data")


def smoke(binary: Path, startup_timeout: float = 60.0,
          calendar_server_url: str | None = None, calendar_import: bool = False) -> None:
    if calendar_server_url is not None:
        calendar_server_url = _local_calendar_url(calendar_server_url)
    binary = binary.resolve(strict=True)
    logs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sidecar-smoke-") as temporary:
        root = Path(temporary)
        env = os.environ.copy()
        for key, directory in {
            "HOME": "home", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
            "XDG_CACHE_HOME": "cache", "XDG_STATE_HOME": "state", "HF_HOME": "hf",
        }.items():
            path = root / directory
            path.mkdir()
            env[key] = str(path)
        db = root / "journal.db"
        env.update(JOURNAL_DB_PATH=str(db), MEDITATIONS_HOST="127.0.0.1",
                   MEDITATIONS_PORT="0", HF_HUB_OFFLINE="1",
                   JOURNAL_SCHEDULED_REVIEWS="false")
        process = subprocess.Popen([str(binary)], cwd=root, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace")
        lines: queue.Queue[str | None] = queue.Queue()

        def read_logs() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    logs.append(line)
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_logs, daemon=True)
        reader.start()
        failure: Exception | None = None
        try:
            deadline = time.monotonic() + startup_timeout
            while True:
                if process.poll() is not None:
                    raise SmokeError(f"backend exited before readiness (exit {process.returncode})")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SmokeError("startup readiness deadline exceeded")
                try:
                    line = lines.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    continue
                if line is None:
                    process.wait(timeout=max(0.01, remaining))
                    raise SmokeError(f"backend closed logs before readiness (exit {process.returncode})")
                match = re.search(r"Uvicorn running on http://127\.0\.0\.1:(\d+)", line)
                if match:
                    base = f"http://127.0.0.1:{int(match[1])}"
                    break

            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def request(method: str, path: str, expected: int, payload=None, *, raw=False):
                data = None if payload is None else json.dumps(payload).encode()
                req = urllib.request.Request(base + path, data=data, method=method,
                                             headers={"Content-Type": "application/json"})
                try:
                    response = opener.open(req, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    body_bytes = response.read()
                    if response.status != expected:
                        body = body_bytes.decode(errors="replace")
                        raise SmokeError(f"{method} {path}: expected {expected}, got {response.status}: {body}")
                    if raw:
                        return body_bytes
                    body = body_bytes.decode()
                    if expected == 204:
                        return None
                    try:
                        return json.loads(body)
                    except ValueError as error:
                        raise SmokeError(f"{method} {path}: invalid JSON: {body}") from error

            def require(condition: bool, message: str) -> None:
                if not condition:
                    raise SmokeError(message)

            require(request("GET", "/api/health", 200) == {"status": "ok"}, "invalid health response")
            collection = request("POST", "/api/lists", 201, {"name": "Smoke list"})
            list_path = "/api/lists/" + collection["id"]
            require(request("GET", list_path, 200)["name"] == "Smoke list", "list read mismatch")
            require(request("PATCH", list_path, 200, {"name": "Updated list"})["name"] == "Updated list", "list patch mismatch")
            task = request("POST", "/api/tasks", 201, {"title": "Smoke task", "list_id": collection["id"]})
            task_path = "/api/tasks/" + task["id"]
            fetched = request("GET", task_path, 200)
            require(fetched["title"] == "Smoke task" and fetched["list_id"] == collection["id"], "linked task read mismatch")
            require(request("PATCH", task_path, 200, {"title": "Updated task"})["title"] == "Updated task", "task patch mismatch")
            request("DELETE", task_path, 204)
            request("GET", task_path, 404)
            request("DELETE", list_path, 204)
            request("GET", list_path, 404)
            if calendar_server_url is not None:
                _smoke_calendar(request, require, calendar_server_url)
            if calendar_import:
                _smoke_calendar_import(request, require)
            recovery_list = request("POST", "/api/lists", 201, {"name": "Recovery list"})
            recovery_task = request("POST", "/api/tasks", 201,
                                    {"title": "Recovery task", "list_id": recovery_list["id"]})
            backup = root / "backup.db"
            backup.write_bytes(request("POST", "/api/backup", 200, raw=True))
            # Even empty journal text reaches optional embeddings; omit journal writes.
            require(db.is_file() and db.stat().st_size > 0, "isolated database was not created")
            require(process.poll() is None, "backend exited during smoke checks")
        except Exception as error:
            failure = error
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
        if failure is None:
            try:
                _smoke_restore(binary, backup, root / "restored.db", env,
                               recovery_list["id"], recovery_task["id"])
            except Exception as error:
                failure = error
        if failure is not None:
            raise SmokeError(f"{failure}\n--- backend logs ---\n{''.join(logs)}") from failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--calendar-server-url", help="disposable loopback CalDAV test server only")
    parser.add_argument('--calendar-import', action='store_true', help='exercise opaque local calendar imports')
    args = parser.parse_args()
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    try:
        smoke(args.binary, args.startup_timeout, args.calendar_server_url, args.calendar_import)
    except (OSError, SmokeError) as error:
        print(error, file=sys.stderr)
        return 1
    print("Packaged backend smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
