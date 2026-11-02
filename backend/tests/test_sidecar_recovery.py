from __future__ import annotations

import sys


def test_sidecar_restore_dispatch_does_not_start_server_or_watcher(monkeypatch):
    import sidecar_main
    from app import recovery

    calls = []
    monkeypatch.setattr(sys, "argv", ["meditations-backend", "restore", "backup.db", "--database", "target.db"])
    monkeypatch.setattr(recovery, "main", lambda: calls.append("restore"))

    def unexpected(*args, **kwargs):
        raise AssertionError("Restore must not start a server or parent watcher")

    monkeypatch.setattr(sidecar_main.threading, "Thread", unexpected)
    monkeypatch.setattr("uvicorn.run", unexpected)
    sidecar_main.main()
    assert calls == ["restore"]
