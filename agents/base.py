"""Base class for all research agents in the pipeline."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional

from blackboard import Blackboard
from live_trace.hooks import trace_agent_end, trace_agent_error, trace_agent_start
from llm.client import LLMClient, default_llm_client, extract_json
from message import Message, MessageBus, MessageType

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(
        self,
        name: str,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 1,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.name = name
        self.blackboard = blackboard
        self.bus = bus
        self.phase = phase
        self.llm = llm_client or default_llm_client
        self.config = self.llm.get_agent_config(self.name)
        self.bus.subscribe(self.name, self.on_message)

    @property
    def phase_name(self) -> str:
        mapping = {
            "MemoryAgent": "phase_0_memory_retrieve" if self.phase == 0 else "phase_9_memory_save",
            "ResearcherAgent": "phase_1_search_and_papers",
            "PaperReaderAgent": "phase_1_search_and_papers",
            "SurveyorAgent": "phase_2_surveyor",
            "GapAnalystAgent": "phase_3_gap_analyst",
            "IdeatorAgent": "phase_4_ideator",
            "TechStackAgent": "phase_5_stack_and_eval",
            "EvaluatorAgent": "phase_5_stack_and_eval",
            "GradingAlignmentAgent": "phase_7_rubric_grading",
            "ReporterAgent": "phase_8_report",
        }
        return mapping.get(self.name, f"phase_{self.phase}_{self.name.lower()}")

    def record_phase_error(self, exc: Exception) -> None:
        err_msg = str(exc)
        self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = err_msg
        if self.name != self.phase_name:
            self.blackboard.metadata.setdefault("phase_errors", {})[self.name] = err_msg

    def on_message(self, message: Message) -> None:
        """Override in subclasses to react to incoming bus messages."""
        pass

    def send_message(self, recipient: str, msg_type: MessageType, payload: Any) -> None:
        msg = Message(sender=self.name, recipient=recipient, type=msg_type, payload=payload)
        self.bus.publish(msg)

    async def run_phase(self, *args: Any, **kwargs: Any) -> Any:
        """Executes the agent's phase logic wrapped in live trace hooks."""
        trace_agent_start(self.name, phase=self.phase)
        try:
            if inspect.iscoroutinefunction(self._run):
                result = await self._run(*args, **kwargs)
            else:
                result = await asyncio.to_thread(self._run, *args, **kwargs)
            summary = self.summarize(result)
            trace_agent_end(self.name, phase=self.phase, summary=summary)
            return result
        except Exception as exc:
            trace_agent_error(self.name, str(exc))
            logger.error("Agent %s failed: %s", self.name, exc, exc_info=True)
            raise

    async def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Subclasses must implement _run")

    def summarize(self, result: Any) -> str:
        if isinstance(result, str):
            return result[:200]
        if isinstance(result, list):
            return f"Generated {len(result)} items"
        if isinstance(result, dict):
            return f"Generated {len(result)} keys: {', '.join(list(result.keys())[:3])}"
        return f"Completed phase {self.phase}"

    def parse_json_response(self, text: str) -> Any:
        """Extracts and parses JSON from LLM output (handles code fences, raw JSON)."""
        return extract_json(text)
