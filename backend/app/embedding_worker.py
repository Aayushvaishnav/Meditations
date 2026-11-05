"""Serialized off-loop execution for optional local embeddings."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class EmbeddingWorker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embeddings")
        self._closed = False

    async def run(self, function: Callable[[], T]) -> T:
        if self._closed:
            raise RuntimeError("Embedding worker is shut down")
        # The executor, not an asyncio lock, owns serialization; cancelling an
        # await cannot release a still-running model call to concurrent access.
        future = self._executor.submit(function)
        return await asyncio.wrap_future(future)

    async def shutdown(self) -> None:
        self._closed = True
        drain = asyncio.create_task(asyncio.to_thread(
            self._executor.shutdown, wait=True, cancel_futures=True,
        ))
        cancelled = False
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                cancelled = True
        drain.result()
        if cancelled:
            raise asyncio.CancelledError


_worker: EmbeddingWorker | None = None


def start_embedding_worker() -> None:
    global _worker
    if _worker is None:
        _worker = EmbeddingWorker()


async def run_embedding(function: Callable[[], T]) -> T:
    start_embedding_worker()
    assert _worker is not None
    return await _worker.run(function)


async def shutdown_embedding_worker() -> None:
    """Drain running inference and close threads; call at application shutdown."""
    global _worker
    if _worker is not None:
        try:
            await _worker.shutdown()
        finally:
            _worker = None
