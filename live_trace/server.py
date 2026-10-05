"""Local-only websocket server: forwards every event emitted via
broadcaster.emit() to every connected browser tab showing panel.html.

No auth, no TLS -- this is a single-user, localhost-only dev panel
(matches the project's local-hosting scope), not something to expose
beyond your own machine.
"""
from __future__ import annotations

import asyncio
import logging
import threading

import websockets

from .broadcaster import broadcaster

logger = logging.getLogger(__name__)


async def _handle_client(websocket) -> None:
    """Forward broadcaster events to this one browser tab until it (or
    the server) closes the connection.

    Races queue.get() against websocket.wait_closed() rather than just
    looping on queue.get() -- a handler blocked purely on an empty
    queue never notices a closed connection (it isn't calling send/recv
    to trigger ConnectionClosed), which otherwise makes server shutdown
    hang waiting for this task to finish.
    """
    queue = broadcaster.register()
    logger.info("Trace panel connected (%d total)", len(broadcaster))
    closed = asyncio.ensure_future(websocket.wait_closed())
    try:
        while True:
            get_next = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({get_next, closed}, return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                get_next.cancel()
                break
            message = get_next.result()
            try:
                await websocket.send(message)
            except websockets.ConnectionClosed:
                break
    finally:
        closed.cancel()
        broadcaster.unregister(queue)
        logger.info("Trace panel disconnected (%d remaining)", len(broadcaster))


async def run_server(host: str = "localhost", port: int = 8765) -> None:
    """Runs forever. Call via asyncio.create_task(run_server()) if your
    main.py is already async, or via start_in_background_thread() below
    if it isn't."""
    broadcaster.bind_loop(asyncio.get_running_loop())
    async with websockets.serve(_handle_client, host, port):
        logger.info("Trace server listening on ws://%s:%d", host, port)
        await asyncio.Future()  # run until cancelled


def start_in_background_thread(host: str = "localhost", port: int = 8765) -> threading.Thread:
    """Runs the trace server in a daemon thread with its own event
    loop, so it works regardless of whether the rest of your pipeline
    is sync or async. Call this once, near the top of main.py, before
    running a research pipeline -- events emitted before the server
    thread finishes starting are silently dropped (see broadcaster.py),
    so start it first."""

    def _target() -> None:
        asyncio.run(run_server(host, port))

    thread = threading.Thread(target=_target, daemon=True, name="live-trace-server")
    thread.start()
    return thread


def main() -> None:
    """Run the server standalone: `python -m live_trace.server`."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
