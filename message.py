"""In-memory publish/subscribe message bus for agent-to-agent communication.

Supports point-to-point and broadcast messaging between agents, with automatic
event broadcasting to the live_trace panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List

from live_trace.hooks import trace_message


class MessageType(Enum):
    TASK_START = auto()
    TASK_COMPLETE = auto()
    SEARCH_REQUEST = auto()
    SEARCH_RESULT = auto()
    PAPERS_FOUND = auto()
    SOLUTIONS_IDENTIFIED = auto()
    GAPS_IDENTIFIED = auto()
    FEATURES_PROPOSED = auto()
    TECH_STACK_PROPOSED = auto()
    EVALUATION_COMPLETE = auto()
    VERIFICATION_RESULT = auto()
    RUBRIC_AUDIT_COMPLETE = auto()
    REPORT_GENERATED = auto()
    ERROR = auto()
    INFO = auto()


@dataclass
class Message:
    sender: str
    recipient: str  # Specific agent name or "*" for broadcast
    type: MessageType
    payload: Any
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def preview(self) -> str:
        if isinstance(self.payload, dict):
            preview_items = [f"{k}: {str(v)[:40]}" for k, v in list(self.payload.items())[:3]]
            return ", ".join(preview_items)
        return str(self.payload)[:150]


class MessageBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Message], None]]] = {}
        self._history: List[Message] = []

    def subscribe(self, agent_name: str, callback: Callable[[Message], None]) -> None:
        if agent_name not in self._subscribers:
            self._subscribers[agent_name] = []
        self._subscribers[agent_name].append(callback)

    def publish(self, message: Message) -> None:
        self._history.append(message)
        trace_message(
            sender=message.sender,
            recipient=message.recipient,
            message_type=message.type.name,
            preview=message.preview(),
        )

        if message.recipient == "*":
            for name, callbacks in self._subscribers.items():
                if name != message.sender:
                    for cb in callbacks:
                        cb(message)
        else:
            if message.recipient in self._subscribers:
                for cb in self._subscribers[message.recipient]:
                    cb(message)

    @property
    def history(self) -> List[Message]:
        return list(self._history)
