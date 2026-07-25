"""Small asyncio helper for scheduling background work.

``PeriodicTask`` runs a coroutine factory on a fixed interval, absorbs
per-tick exceptions, and stops cleanly on cancel. Used by upcoming
job-retention pruning and SQLite backup automation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable


log = logging.getLogger("project_remedy.backend.scheduler")


CoroFactory = Callable[[], Awaitable[None]]


class PeriodicTask:
    """Run ``coro_factory`` every ``interval_seconds`` until stopped.

    The factory is re-invoked each tick so it returns a fresh coroutine.
    Exceptions from the tick are logged and swallowed; the loop continues.
    The first tick fires AFTER the first sleep, not on start.
    """

    def __init__(
        self,
        coro_factory: CoroFactory,
        interval_seconds: float,
        name: str | None = None,
    ) -> None:
        self._coro_factory = coro_factory
        self._interval = interval_seconds
        self._name = name or "periodic-task"
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name=self._name)

    async def stop(self) -> None:
        if self._task is None:
            return
        task = self._task
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("PeriodicTask %s tick raised", self._name)
