"""CoordinatorAgent: orchestrates the full multi-agent research pipeline."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from blackboard import Blackboard
from live_trace.hooks import (
    trace_agent_end,
    trace_agent_error,
    trace_agent_start,
    trace_run_end,
    trace_run_start,
)
from llm.client import LLMClient
from message import MessageBus
from storage.db import save_run
from verification.pipeline import VerificationPipeline

from .evaluator_agent import EvaluatorAgent
from .gap_analyst_agent import GapAnalystAgent
from .grading_alignment_agent import GradingAlignmentAgent
from .ideator_agent import IdeatorAgent
from .memory_agent import MemoryAgent
from .paper_reader_agent import PaperReaderAgent
from .query_planner_agent import QueryPlannerAgent
from .reporter_agent import ReporterAgent
from .researcher_agent import ResearcherAgent
from .surveyor_agent import SurveyorAgent
from .tech_stack_agent import TechStackAgent

logger = logging.getLogger(__name__)


MAX_TOPIC_LENGTH = 1000


class CoordinatorAgent:
    def __init__(
        self,
        topic: str,
        project_context: str = "",
        context: str = "",
        run_id: Optional[str] = None,
        db_path: str = "research_runs.db",
        llm_client: Optional[LLMClient] = None,
        depth_mode: str = "standard",
    ) -> None:
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        self.depth_mode = (depth_mode or "standard").lower()

        # Sanitize and validate topic length boundary
        clean_topic = (topic or "").strip()
        effective_context = (project_context or context or "").strip()
        if len(clean_topic) > MAX_TOPIC_LENGTH:
            lines = [l.strip() for l in clean_topic.splitlines() if l.strip()]
            short_topic = lines[0] if lines else clean_topic[:MAX_TOPIC_LENGTH]
            if len(short_topic) > MAX_TOPIC_LENGTH:
                short_topic = short_topic[:MAX_TOPIC_LENGTH]
            effective_context = f"Topic Background:\n{clean_topic}\n\n{effective_context}".strip()
            clean_topic = short_topic

        self.blackboard = Blackboard(
            run_id=self.run_id,
            topic=clean_topic,
            project_context=effective_context,
            metadata={"phases": {}, "run_id": self.run_id, "depth_mode": self.depth_mode},
        )
        self.bus = MessageBus()
        self.llm = llm_client
        self.db_path = db_path
        self.verification = VerificationPipeline(llm_client=self.llm)

        # Initialize sub-agents
        self.memory_agent = MemoryAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.query_planner = QueryPlannerAgent(self.blackboard, self.bus, phase=0, llm_client=self.llm)
        self.researcher_agent = ResearcherAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.paper_reader_agent = PaperReaderAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.surveyor_agent = SurveyorAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.gap_analyst = GapAnalystAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.ideator_agent = IdeatorAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.tech_stack_agent = TechStackAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.evaluator_agent = EvaluatorAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.grading_agent = GradingAlignmentAgent(self.blackboard, self.bus, llm_client=self.llm)
        self.reporter_agent = ReporterAgent(self.blackboard, self.bus, llm_client=self.llm)

    async def _instrument_phase(self, phase_name: str, coro: Any) -> Any:
        start_t = time.time()
        try:
            res = await coro
            duration = round(time.time() - start_t, 3)
            self.blackboard.metadata.setdefault("phases", {})[phase_name] = {
                "status": "completed",
                "duration_s": duration,
            }
            return res
        except Exception as exc:
            duration = round(time.time() - start_t, 3)
            self.blackboard.metadata.setdefault("phases", {})[phase_name] = {
                "status": "failed",
                "error": str(exc),
                "duration_s": duration,
            }
            raise

    async def run(self, rubric_path: Optional[str] = None) -> Blackboard:
        """Executes the full end-to-end research workflow."""
        trace_run_start(self.run_id, self.blackboard.topic, self.blackboard.project_context)
        logger.info("Starting Research Run %s for topic: '%s'", self.run_id, self.blackboard.topic)
        start_all = time.time()

        try:
            # Phase 0: Memory context retrieval
            await self._instrument_phase(
                "phase_0_memory_retrieve",
                self.memory_agent.run_phase(action="retrieve"),
            )

            # Phase 0.5: Query Planning & Problem Decomposition
            await self._instrument_phase(
                "phase_0_query_plan",
                self.query_planner.run_phase(),
            )

            # Phase 1: Multi-engine web search + Academic paper reader (Parallel)
            max_papers = 20 if self.depth_mode == "deep" else 8
            await self._instrument_phase(
                "phase_1_search_and_papers",
                asyncio.gather(
                    self.researcher_agent.run_phase(),
                    self.paper_reader_agent.run_phase(max_papers=max_papers),
                ),
            )

            # Phase 2: State-of-the-Art & Landscape Survey
            solutions = await self._instrument_phase(
                "phase_2_surveyor",
                self.surveyor_agent.run_phase(),
            )
            if solutions:
                await self.verification.verify_layer2_claims(
                    "SurveyorAgent",
                    " ".join([f"{s.name}: {s.description}" for s in solutions]),
                    self.blackboard,
                )

            # Phase 3: Gap Analysis
            gaps = await self._instrument_phase(
                "phase_3_gap_analyst",
                self.gap_analyst.run_phase(),
            )
            if gaps:
                await self.verification.verify_layer2_claims(
                    "GapAnalystAgent",
                    " ".join([f"{g.title}: {g.description}" for g in gaps]),
                    self.blackboard,
                )

            # Phase 4: Novel Ideation
            features = await self._instrument_phase(
                "phase_4_ideator",
                self.ideator_agent.run_phase(),
            )
            if features:
                await self.verification.verify_layer2_claims(
                    "IdeatorAgent",
                    " ".join([f"{f.title}: {f.description}" for f in features]),
                    self.blackboard,
                )

            # Phase 5: Tech Stack & Feasibility Evaluation (Parallel)
            await self._instrument_phase(
                "phase_5_stack_and_eval",
                asyncio.gather(
                    self.tech_stack_agent.run_phase(),
                    self.evaluator_agent.run_phase(),
                ),
            )

            # Phase 6: Layer 3 Consistency Audit
            await self._instrument_phase(
                "phase_6_consistency",
                self.verification.verify_layer3_consistency(self.blackboard),
            )

            # Phase 7: Rubric Alignment (if rubric supplied)
            if rubric_path:
                await self._instrument_phase(
                    "phase_7_rubric_grading",
                    self.grading_agent.run_phase(rubric_path=rubric_path),
                )

            # Phase 8: Markdown Report Generation
            report = await self._instrument_phase(
                "phase_8_report",
                self.reporter_agent.run_phase(),
            )

            # Phase 9: Memory digest saving & DB persistence
            await self._instrument_phase(
                "phase_9_memory_save",
                self.memory_agent.run_phase(action="save"),
            )

            total_duration = round(time.time() - start_all, 3)
            self.blackboard.metadata["total_duration_s"] = total_duration

            # Determine if run produced substantive output
            substantive_empty = all(
                len(getattr(self.blackboard, field, [])) == 0
                for field in [
                    "sources",
                    "paper_notes",
                    "existing_solutions",
                    "gaps",
                    "proposed_features",
                    "tech_stack",
                    "evaluations",
                    "claim_verifications",
                    "consistency_issues",
                    "rubric_scores",
                ]
            )

            # Check whether any downstream synthesis phases produced output
            synthesis_empty = all(
                len(getattr(self.blackboard, field, [])) == 0
                for field in [
                    "existing_solutions",
                    "gaps",
                    "proposed_features",
                    "tech_stack",
                    "evaluations",
                    "claim_verifications",
                ]
            )

            # Check if any agent recorded a phase error
            phase_errors = self.blackboard.metadata.get("phase_errors", {})
            has_phase_errors = len(phase_errors) > 0

            if substantive_empty:
                run_status = "completed_empty"
            elif has_phase_errors and synthesis_empty:
                run_status = "completed_degraded"
            elif has_phase_errors:
                run_status = "completed_degraded"
            else:
                run_status = "completed"

            self.blackboard.metadata["status"] = run_status
            if has_phase_errors:
                self.blackboard.metadata["degraded_phases"] = list(phase_errors.keys())

            save_run(self.blackboard, status=run_status, db_path=self.db_path)

            trace_run_end(self.run_id, report_path=f"reports/{self.run_id}_report.md")
            return self.blackboard

        except Exception as exc:
            logger.error("Pipeline failed on run %s: %s", self.run_id, exc, exc_info=True)
            self.blackboard.metadata["error"] = str(exc)
            save_run(self.blackboard, status="failed", db_path=self.db_path)
            raise
