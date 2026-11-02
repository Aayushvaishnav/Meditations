from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
from sqlalchemy.ext.asyncio import AsyncEngine


async def create_backup(engine: AsyncEngine, destination: Path) -> None:
    """Write a consistent SQLite snapshot; shared in-memory connections must be quiescent."""
    async with engine.connect() as connection:
        raw = await connection.get_raw_connection()
        async with aiosqlite.connect(destination) as target:
            worker = asyncio.create_task(raw.driver_connection.backup(target))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # SQLite keeps running on its source thread; retain both connections until done
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not worker.cancelled():
                    worker.exception()
                raise
