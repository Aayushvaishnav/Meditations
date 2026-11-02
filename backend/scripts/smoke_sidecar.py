#!/usr/bin/env python3
"""Exercise a frozen backend in an ephemeral, offline sandbox; stdlib only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


class SmokeError(RuntimeError):
    pass


def smoke(binary: Path, startup_timeout: float = 60.0) -> None:
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

            def request(method: str, path: str, expected: int, payload=None):
                data = None if payload is None else json.dumps(payload).encode()
                req = urllib.request.Request(base + path, data=data, method=method,
                                             headers={"Content-Type": "application/json"})
                try:
                    response = opener.open(req, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    body = response.read().decode()
                    if response.status != expected:
                        raise SmokeError(f"{method} {path}: expected {expected}, got {response.status}: {body}")
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
        if failure is not None:
            raise SmokeError(f"{failure}\n--- backend logs ---\n{''.join(logs)}") from failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    args = parser.parse_args()
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    try:
        smoke(args.binary, args.startup_timeout)
    except (OSError, SmokeError) as error:
        print(error, file=sys.stderr)
        return 1
    print("Packaged backend smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
