"""In-process pub/sub hub for trace events.

One TraceBroadcaster instance (the module-level `broadcaster` below) is
shared by the websocket server (which forwards every event to every
connected browser tab) and by the agent-facing hooks in hooks.py. Kept
separate from the websocket transport so hooks.py never needs to import
`websockets` directly.

Thread-safety: your existing pipeline might call the trace_* hooks from
whatever thread/event loop it already runs on, while the websocket
server runs its own event loop (see server.start_in_background_thread).
`emit()` always hops back onto the server's loop via
`call_soon_threadsafe` once it's known, so it's safe to call from
anywhere -- the same thread, a different thread, sync or async code.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class TraceBroadcaster:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once by server.run_server() when it starts, so emit()
        knows which event loop's thread to deliver onto."""
        self._loop = loop

    def register(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._queues.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[str]) -> None:
        self._queues.discard(queue)

    def emit(self, event_type: str, **fields: Any) -> None:
        """Non-blocking and safe to call from anywhere in the agent
        pipeline. Events emitted before the server has started (or
        while no browser panel is connected) are silently dropped --
        this is a live monitor, not a durable log; SQLite already owns
        the durable run record."""
        if self._loop is None:
            return
        event = {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **fields}
        payload = json.dumps(event, default=str)
        for queue in list(self._queues):
            self._loop.call_soon_threadsafe(queue.put_nowait, payload)

    def __len__(self) -> int:
        return len(self._queues)


# One process-wide instance. hooks.py and server.py both import this so
# every agent in a run shares one broadcaster without it being threaded
# through every constructor.
broadcaster = TraceBroadcaster()
