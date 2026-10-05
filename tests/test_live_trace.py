import asyncio
import json

import websockets

from live_trace.hooks import trace_agent_start
from live_trace.server import run_server


def test_server_broadcasts_emitted_events():
    """Starts the real server (not a mock), connects a real websocket
    client, emits an event through the real hooks/broadcaster path, and
    checks the client actually receives it -- covers the thread-safe
    call_soon_threadsafe delivery path, not just the merge logic."""

    async def scenario():
        server_task = asyncio.create_task(run_server(host="localhost", port=8799))
        await asyncio.sleep(0.2)  # let the server bind before connecting

        try:
            async with websockets.connect("ws://localhost:8799") as client:
                await asyncio.sleep(0.05)  # let the server register this client's queue
                trace_agent_start("ResearcherAgent", phase=1)
                raw = await asyncio.wait_for(client.recv(), timeout=2)
                event = json.loads(raw)
                assert event["type"] == "agent_start"
                assert event["agent"] == "ResearcherAgent"
                assert event["phase"] == 1
                assert "ts" in event
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())


def test_events_dropped_silently_before_server_starts():
    """emit() before any server has bound a loop should not raise --
    it's a live monitor, not a durable log."""
    from live_trace.broadcaster import TraceBroadcaster

    isolated = TraceBroadcaster()
    isolated.emit("agent_start", agent="ResearcherAgent", phase=1)  # must not raise
