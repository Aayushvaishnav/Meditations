"""Offline, cooperative-owner SQLite recovery and private online checkpoints."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

import sqlite_vec
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import LATEST_VERSION, MIGRATIONS, migrate


class RecoveryError(RuntimeError):
    """A backup cannot safely replace the destination."""


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw")
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except BaseException:
        conn.close()
        raise
    return conn


def _validate(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RecoveryError("Database integrity check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RecoveryError("Database foreign key check failed")


def _private_file(directory: Path, prefix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".db", dir=directory)
    os.close(fd)
    return Path(name)


def _copy(source: Path, target: Path) -> None:
    with closing(_connect(source, readonly=True)) as src:
        _validate(src)
        with closing(_connect(target)) as dst:
            src.backup(dst)
            _validate(dst)


def checkpoint_database(source: Path, reason: str) -> Path:
    """Save a consistent, mode-0600 snapshot; caller owns any writer lock.

    ``reason`` labels the operation in the unique snapshot filename.
    This helper never migrates and is safe inside the migration entry point.
    """
    source = Path(source)
    if not reason.strip():
        raise ValueError("Checkpoint reason must not be empty")
    directory = source.parent / "recovery"
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    target = _private_file(directory, f"checkpoint-{quote(reason, safe='')}-")
    try:
        _copy(source, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def _contract(execute) -> dict[str, tuple]:
    tables = execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    result = {}
    for (name,) in tables:
        quoted = name.replace('"', '""')
        columns = [tuple(row) for row in execute(f'PRAGMA table_info("{quoted}")').fetchall()]
        foreign_keys = sorted(tuple(row)[2:] for row in execute(
            f'PRAGMA foreign_key_list("{quoted}")'
        ).fetchall())
        unique = []
        for index in execute(f'PRAGMA index_list("{quoted}")').fetchall():
            if index[2]:
                index_name = index[1].replace('"', '""')
                unique.append((tuple(tuple(row)[1:] for row in execute(
                    f'PRAGMA index_xinfo("{index_name}")'
                ).fetchall()), index[4]))
        result[name] = (columns, foreign_keys, sorted(unique))
    return result


async def _prepare(stage: Path) -> None:
    with closing(_connect(stage)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > LATEST_VERSION:
            raise RecoveryError(f"Schema version {version} is newer than {LATEST_VERSION}")
        actual = _contract(conn.execute)
    reference = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with reference.begin() as conn:
            # Version zero is the legacy baseline, not an empty application database
            for migration in MIGRATIONS[:max(version, 1)]:
                await migration(conn)
            expected = await conn.run_sync(lambda sync: _contract(sync.exec_driver_sql))
        for table, columns in expected.items():
            if actual.get(table) != columns:
                raise RecoveryError(f"Missing or incompatible schema for table {table}")
    finally:
        await reference.dispose()
    engine = create_async_engine("sqlite+aiosqlite:///" + str(stage.resolve()))
    try:
        await migrate(engine, checkpoint=False)
    finally:
        await engine.dispose()
    with closing(_connect(stage)) as conn:
        _validate(conn)
        conn.execute("PRAGMA journal_mode=DELETE")


async def restore_database(backup: Path, destination: Path) -> Path | None:
    """Restore under exclusive cooperative ownership; return previous DB checkpoint.

    All application connections must be closed before calling; external writers
    that ignore the advisory ownership lock are unsupported. A rejected backup
    never changes the destination. Replacement failures leave the current database
    usable and retain its checkpoint. The input backup is never migrated in place.
    """
    from app.database_lock import DatabaseLock

    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    if backup == destination:
        raise RecoveryError("Backup and destination must be different files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with DatabaseLock(destination):
        stage = _private_file(destination.parent, ".restore-")
        try:
            _copy(backup, stage)
            await _prepare(stage)
            checkpoint = None
            if destination.exists():
                checkpoint = checkpoint_database(destination, "pre-restore")
                with closing(_connect(destination)) as conn:
                    busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if busy:
                        raise RecoveryError("Destination has active SQLite users")
                    conn.execute("PRAGMA journal_mode=DELETE")
            elif any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm")):
                raise RecoveryError("Destination has orphaned SQLite sidecars")
            os.replace(stage, destination)
            return checkpoint
        except sqlite3.Error as exc:
            raise RecoveryError(f"SQLite recovery failed: {exc}") from exc
        finally:
            stage.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--database", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        checkpoint = asyncio.run(restore_database(args.backup, args.database))
    except (RecoveryError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Restore failed: {exc}\n")
    print(f"Restored {args.database}")
    if checkpoint is not None:
        print(f"Previous database checkpoint: {checkpoint}")


if __name__ == "__main__":
    main()
