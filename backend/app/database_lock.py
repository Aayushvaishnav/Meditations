from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class DatabaseInUseError(RuntimeError):
    """Another cooperating process owns this database."""


class DatabaseLock:
    """Process ownership shared by backends and offline recovery commands."""

    def __init__(self, database: Path) -> None:
        self.path = Path(f"{database.resolve()}.lock")
        self._file: BinaryIO | None = None

    def __enter__(self) -> DatabaseLock:
        if self._file is not None:
            raise RuntimeError("Database lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(fd, "r+b")
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise DatabaseInUseError(
                f"Database is in use: {self.path.with_suffix('')}. "
                "Quit the desktop app (including its tray icon) and stop all backends first."
            ) from exc
        self._file = stream
        return self

    def __exit__(self, *_: object) -> None:
        if self._file is not None:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None
