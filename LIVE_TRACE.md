# Live trace panel — drop-in addition

Implements project roadmap §9, Phase 1: a way to *watch* the 11-agent
pipeline run, instead of staring at a blank terminal until `report.md`
appears. Local only — a plain HTML/JS page connects over a websocket to
a small Python server running on your own machine. No external
service, no account, nothing leaves localhost.

**Tested for real, not just unit-tested against fakes:** the test suite
starts the actual websocket server, connects a real client, and
confirms an event emitted through the real hook path is actually
delivered — including the thread-safety path (`call_soon_threadsafe`)
that matters once this runs alongside a sync pipeline. All passing.
What's *not* tested here: wiring the hooks into your actual
`BaseAgent`/`MessageBus`/`CoordinatorAgent` — that needs your real
files, shown as integration snippets below.

## What's in this drop

```
research_agent/
  live_trace/
    __init__.py          # exports the hooks + server entry points
    broadcaster.py         # thread-safe pub/sub hub (the shared state)
    hooks.py                 # trace_run_start / trace_agent_start / trace_message / ...
    server.py                  # websocket server + start_in_background_thread()
    panel.html                  # the frontend -- open this file directly in a browser
  tests/
    test_live_trace.py           # real server + real client integration test
```

(Named `live_trace`, not `trace`, so it doesn't shadow Python's stdlib
`trace` module.)

Copy `live_trace/` and `tests/test_live_trace.py` into your existing
`research_agent/` project root, same as the search orchestrator drop.

## Setup

**1. Add to `requirements.txt`:**
```
websockets>=12.0
```

**2. Start the server** — pick whichever matches how your pipeline runs.
If `main.py` doesn't already use `asyncio`:
```python
# main.py, near the top, before running the Coordinator
from live_trace import start_in_background_thread

start_in_background_thread()  # ws://localhost:8765, daemon thread, safe to call once per process
```
If your Coordinator's pipeline is already async, you can instead do
`asyncio.create_task(run_server())` inside your existing event loop —
either works, `start_in_background_thread` is just the option that
doesn't care either way.

**3. Open `live_trace/panel.html`** directly in a browser (double-click
it, or `open`/`xdg-open` it from the terminal — no dev server needed
for the HTML itself). It connects to `ws://localhost:8765` on load and
shows "No run in progress" until it sees a `run_start` event.

**4. Wire the hooks into your pipeline.** This is the one part that
needs your actual files — shown here as the shape to match:

```python
# agents/coordinator_agent.py
from live_trace import trace_run_start, trace_run_end

class CoordinatorAgent:
    async def run(self, topic: str, project_context: str):
        run_id = ...  # however you currently generate it
        trace_run_start(run_id, topic, project_context)
        try:
            ...  # your existing phase-by-phase orchestration
        finally:
            trace_run_end(run_id, report_path=str(report_path))
```

```python
# agents/base.py
from live_trace import trace_agent_start, trace_agent_end, trace_agent_error

class BaseAgent:
    async def run_phase(self, *args, **kwargs):
        trace_agent_start(self.__class__.__name__, phase=self.phase)
        try:
            result = await self._run(*args, **kwargs)  # your existing logic
            trace_agent_end(self.__class__.__name__, phase=self.phase, summary=self.summarize(result))
            return result
        except Exception as exc:
            trace_agent_error(self.__class__.__name__, str(exc))
            raise
```

```python
# message.py
from live_trace import trace_message

class MessageBus:
    def publish(self, message: Message):
        trace_message(
            sender=message.sender,
            recipient=message.recipient,
            message_type=message.type.name,
            preview=str(message.payload)[:150],
        )
        ...  # your existing dispatch logic
```

```python
# blackboard.py -- call this wherever you append to a tracked list
from live_trace import trace_blackboard_update

def add_source(self, source: Source):
    self.sources.append(source)
    trace_blackboard_update("sources", count=len(self.sources))
```

The panel's stat row currently looks for these five field names:
`sources`, `existing_solutions`, `gaps`, `proposed_features`,
`evaluations`. Use those names in `trace_blackboard_update` calls (or
edit `STAT_FIELDS` in `panel.html` if your Blackboard's field names
differ).

## Running it

```bash
cd research_agent
pip install -r requirements.txt
# terminal 1
open live_trace/panel.html   # or just double-click it
# terminal 2
python main.py --topic "on-device speech diarization" --context "meeting notes app" --live-trace
```
Watch the panel update live: each agent lights up as it starts,
messages scroll through the feed as they cross the bus, and the
Blackboard stat row climbs as sources/gaps/features get added.

## Design notes / things to know

- **No auth, no TLS, localhost only** — matches the project's
  single-user local-hosting scope (SDLC doc §1/§3). Don't change the
  bind host to `0.0.0.0` unless you also add authentication; there's
  nothing stopping another process on your machine (or, if you did
  expose it, another machine) from connecting and reading your trace.
- **Live-only, not durable.** Events emitted before the server starts,
  or while no browser tab is connected, are silently dropped — SQLite
  already owns the durable run record (per the project's persistence
  decision); this panel is for watching a run *as it happens*, not
  reviewing one after the fact. That's what the Phase 6 Streamlit
  run-browser is for.
- **Multiple tabs work fine** — `broadcaster` fans out to every
  connected client independently; opening the panel twice just gives
  you two synced views.
- **Thread-safety was the real bug to get right here**, not the UI:
  `broadcaster.emit()` uses `call_soon_threadsafe` so it's safe to call
  from your pipeline's thread regardless of which thread the websocket
  server's event loop is running on. The first version of the server's
  per-connection handler also had a real shutdown-hang bug (a handler
  blocked on `queue.get()` never notices the client disconnected,
  which stalls the whole server's shutdown) — fixed by racing
  `queue.get()` against `websocket.wait_closed()`; see the comment in
  `server.py` if you're curious.
- **The stat labels and agent list are not hardcoded to the 11-agent
  roster** — the timeline renders whatever agent names it actually
  sees `agent_start` events for, in the order they first appear, so it
  won't need edits as you add `TechStackAgent`, `PaperReaderAgent`, etc.
