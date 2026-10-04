"""Fire-and-forget background tasks that survive client disconnects and are not garbage-collected."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("tollgate.tasks")
_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_done)


def _done(task: asyncio.Task[Any]) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.error("background task failed", exc_info=task.exception(), extra={"task": task.get_name()})


async def drain(wait_seconds: float = 5.0) -> None:
    """Wait for in-flight tasks on shutdown."""
    if _tasks:
        await asyncio.wait(set(_tasks), timeout=wait_seconds)
