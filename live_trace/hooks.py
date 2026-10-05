"""Thin, agent-facing wrappers around the shared broadcaster. Call
these from BaseAgent / MessageBus / CoordinatorAgent -- they're the
only integration point the rest of the pipeline needs to import."""
from __future__ import annotations

from .broadcaster import broadcaster


def trace_run_start(run_id: str, topic: str, project_context: str = "") -> None:
    broadcaster.emit("run_start", run_id=run_id, topic=topic, project_context=project_context)


def trace_run_end(run_id: str, report_path: str | None = None) -> None:
    broadcaster.emit("run_end", run_id=run_id, report_path=report_path)


def trace_agent_start(agent: str, phase: int | str | None = None) -> None:
    broadcaster.emit("agent_start", agent=agent, phase=phase)


def trace_agent_end(agent: str, phase: int | str | None = None, summary: str = "") -> None:
    broadcaster.emit("agent_end", agent=agent, phase=phase, summary=summary[:300])


def trace_agent_error(agent: str, message: str) -> None:
    broadcaster.emit("agent_error", agent=agent, message=message[:300])


def trace_message(sender: str, recipient: str, message_type: str, preview: str = "") -> None:
    """Call this from MessageBus.publish() (or wherever a Message
    actually gets handed off) with a short human-readable preview of
    its payload -- not the raw payload itself, to keep the panel and
    the websocket frame small."""
    broadcaster.emit(
        "message", sender=sender, recipient=recipient, message_type=message_type, preview=preview[:200]
    )


def trace_blackboard_update(field: str, count: int | None = None, detail: str = "") -> None:
    """Call this whenever an agent appends to a Blackboard list
    (sources, gaps, proposed_features, ...). `count` should be the new
    total length of that list."""
    broadcaster.emit("blackboard_update", field=field, count=count, detail=detail[:200])
