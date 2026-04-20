"""Per-URI read coalescing and a process-global write lock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

_read_locks: dict[str, asyncio.Lock] = {}
_read_locks_guard = asyncio.Lock()

write_lock = asyncio.Lock()


class WriteLock:
    """Async context manager wrapping the module-level write :class:`asyncio.Lock`."""

    async def __aenter__(self) -> None:
        await write_lock.acquire()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        write_lock.release()


async def single_flight_read(uri: str, fetch: Callable[[], Awaitable[T]]) -> T:
    """Serialize concurrent callers for ``uri``; ``fetch`` runs once per wait queue."""
    async with _read_locks_guard:
        lock = _read_locks.get(uri)
        if lock is None:
            lock = asyncio.Lock()
            _read_locks[uri] = lock
    async with lock:
        return await fetch()
