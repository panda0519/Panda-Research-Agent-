"""End-to-end backend integration tests for browser workflow."""
import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from agents.coordinator_agent import CoordinatorAgent
from blackboard import Blackboard, PaperNote, Source
from browser_inputs import resolve_run_inputs
from storage.db import get_run, list_runs


def _configure_mock_coordinator(coordinator: CoordinatorAgent) -> None:
    """Configures a CoordinatorAgent with mock LLM responses and search for offline execution."""
    def mock_generate(prompt, **kwargs):
        if "Extract up to 5 key atomic factual claims" in prompt:
            return '[{"claim_text": "PyAnnote achieves 5% DER", "cited_urls": ["https://arxiv.org/abs/2101.0001"], "status": "CONFIRMED", "rationale": "Backed by paper."}]'
        if "grading / evaluation criteria" in prompt or "Score the research artifacts against each criterion" in prompt:
            return '[{"criterion": "Depth of Literature", "weight": 1.0, "score": 9.0, "strengths": "Cites recent papers", "weaknesses": "None", "evidence_citations": ["GAP-01"]}]'
        if "Extract 3 to 6 prominent existing solutions" in prompt:
            return '[{"name": "PyAnnote Audio", "category": "open_source", "description": "Audio diarization toolkit.", "strengths": ["High accuracy"], "limitations": ["Batch oriented"], "sources": ["https://arxiv.org/abs/2101.0001"]}]'
        if "Identify 3 to 5 critical gaps" in prompt:
            return '[{"gap_id": "GAP-01", "category": "technical", "title": "High Latency", "description": "Existing models require >5s audio buffers.", "evidence": ["PyAnnote limitations"], "severity": "critical"}]'
        if "Design 3 to 5 high-impact, novel features" in prompt:
            return '[{"feature_id": "FEAT-01", "title": "Chunked Causal Diarizer", "description": "Streaming audio encoder with temporal memory.", "target_gap_ids": ["GAP-01"], "architecture_notes": "INT8 ONNX graph.", "novelty_rationale": "Reduces latency."}]'
        if "Recommend a practical, modern technology stack" in prompt:
            return '[{"layer": "ai_orchestration", "selected_tech": "ONNX Runtime", "alternatives_considered": ["TFLite"], "rationale": "ARM64 SIMD support."}]'
        if "Evaluate the following proposed features" in prompt:
            return '[{"feature_id": "FEAT-01", "feasibility_score": 5, "complexity_score": 3, "risk_level": "low", "risks": ["Turn-taking cache"], "mitigations": ["Hysteresis"], "overall_assessment": "Highly viable."}]'
        if "Examine the synthesized findings from different agents for contradictions" in prompt:
            return '[]'
        return "General response"

    coordinator.llm = coordinator.researcher_agent.llm
    coordinator.llm.generate = mock_generate
    for agent in [
        coordinator.surveyor_agent,
        coordinator.gap_analyst,
        coordinator.ideator_agent,
        coordinator.tech_stack_agent,
        coordinator.evaluator_agent,
        coordinator.grading_agent,
        coordinator.reporter_agent,
        coordinator.verification.layer2,
        coordinator.verification.layer3,
    ]:
        agent.llm = coordinator.llm
        agent.llm.generate = mock_generate

    async def mock_fetch_all(query, max_papers=5):
        return [
            PaperNote(
                title="End-to-End Neural Diarization with SincNet",
                authors=["Alice Doe", "Bob Roe"],
                year=2024,
                url="https://arxiv.org/abs/2401.0001",
                source_api="arxiv",
                abstract="Proposes streaming diarization.",
                takeaways="Enables sub-100ms speaker turns.",
            )
        ], []

    coordinator.paper_reader_agent._fetch_all = mock_fetch_all

    from unittest.mock import AsyncMock
    coordinator.surveyor_agent.openalex.search_works = AsyncMock(return_value=[])
    coordinator.surveyor_agent.crossref.search_works = AsyncMock(return_value=[])
    coordinator.gap_analyst.openalex.search_works = AsyncMock(return_value=[])
    coordinator.gap_analyst.crossref.search_works = AsyncMock(return_value=[])
    coordinator.tech_stack_agent.github.get_repo_health = AsyncMock(return_value=None)

    async def mock_search(query, **kwargs):
        return [
            Source(
                url="https://mock.example.com/diarization-review",
                title="Real-time Speech Diarization Review",
                snippet="Review of state of the art streaming diarization approaches.",
                engines=["claude_web_search", "tavily"],
            )
        ]

    coordinator.researcher_agent.orchestrator.search = mock_search




def test_backend_offline_execution_topic_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_browser_runs.db")
        resolved = resolve_run_inputs(
            topic="Streaming Speech Diarization",
            context="Latency < 100ms",
        )
        assert resolved.is_valid is True

        coordinator = CoordinatorAgent(
            topic=resolved.topic,
            project_context=resolved.context,
            db_path=db_file,
        )
        _configure_mock_coordinator(coordinator)

        bb = asyncio.run(coordinator.run())
        assert isinstance(bb, Blackboard)
        assert bb.topic == "Streaming Speech Diarization"

        # Verify persisted run record
        runs = list_runs(db_path=db_file)
        assert len(runs) == 1
        assert runs[0]["topic"] == "Streaming Speech Diarization"

        record = get_run(coordinator.run_id, db_path=db_file)
        assert record is not None
        assert record["status"] == "completed"


def test_backend_offline_execution_file_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_browser_runs.db")
        file_text = "# On-device Audio Segmentation\nConstraints: Run on edge devices with minimal DRAM."
        resolved = resolve_run_inputs(
            topic="",
            context="",
            problem_file_name="problem.md",
            problem_file_text=file_text,
        )
        assert resolved.is_valid is True
        assert resolved.topic == "# On-device Audio Segmentation"

        coordinator = CoordinatorAgent(
            topic=resolved.topic,
            project_context=resolved.context,
            db_path=db_file,
        )
        _configure_mock_coordinator(coordinator)

        bb = asyncio.run(coordinator.run())
        assert isinstance(bb, Blackboard)

        runs = list_runs(db_path=db_file)
        assert len(runs) == 1
        assert runs[0]["topic"] == "# On-device Audio Segmentation"


def test_temp_rubric_file_cleanup_and_suffix():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_browser_runs.db")

        # Test with markdown rubric
        rubric_content = """# Rubric
- [ ] Multi-Engine Evidence Depth (weight: 50%)
- [ ] Tech Stack Layering (weight: 50%)
"""
        rubric_filename = "custom_rubric.md"
        suffix = Path(rubric_filename).suffix
        assert suffix == ".md"

        temp_rubric_path = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
            tmp.write(rubric_content)
            temp_rubric_path = tmp.name

        assert os.path.exists(temp_rubric_path)
        assert temp_rubric_path.endswith(".md")

        try:
            coordinator = CoordinatorAgent(
                topic="Speech Diarization with Rubric",
                project_context="Test",
                db_path=db_file,
            )
            _configure_mock_coordinator(coordinator)
            bb = asyncio.run(coordinator.run(rubric_path=temp_rubric_path))
            assert len(bb.rubric_scores) > 0
        finally:
            if temp_rubric_path and os.path.exists(temp_rubric_path):
                os.unlink(temp_rubric_path)

        # Confirm temporary file is deleted
        assert not os.path.exists(temp_rubric_path)
        assert Path(temp_rubric_path).parent == Path(tempfile.gettempdir())


def test_browser_run_with_session_api_keys_scoped_injection():
    from api_key_manager import scoped_env_override

    orig_anthropic = os.environ.get("ANTHROPIC_API_KEY")
    orig_tavily = os.environ.get("TAVILY_API_KEY")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_browser_runs.db")

        fake_session_keys = {
            "ANTHROPIC_API_KEY": "sk-ant-session-override-12345",
            "TAVILY_API_KEY": "tvly-session-override-67890",
        }

        # Simulate browser run with session key overrides
        with scoped_env_override(fake_session_keys):
            assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-session-override-12345"
            assert os.environ["TAVILY_API_KEY"] == "tvly-session-override-67890"

            coordinator = CoordinatorAgent(
                topic="Session Key Injection Run",
                project_context="Testing temporary scoped overrides",
                db_path=db_file,
            )
            _configure_mock_coordinator(coordinator)
            bb = asyncio.run(coordinator.run())
            assert isinstance(bb, Blackboard)
            assert bb.topic == "Session Key Injection Run"

        # Assert environment variables restored completely
        assert os.environ.get("ANTHROPIC_API_KEY") == orig_anthropic
        assert os.environ.get("TAVILY_API_KEY") == orig_tavily


def test_start_run_applies_scoped_env_and_executes(monkeypatch):
    from browser import start_run

    orig_anthropic = os.environ.get("ANTHROPIC_API_KEY")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_start_run.db")
        fake_keys = {"ANTHROPIC_API_KEY": "sk-ant-start-run-key-999"}

        # Patch CoordinatorAgent.__init__ and run to test wrapper behavior
        observed_env = {}

        def mock_init(self, topic, project_context, db_path):
            self.topic = topic
            self.project_context = project_context
            self.db_path = db_path
            self.run_id = "test_run_123"

        async def mock_run(self, rubric_path=None):
            observed_env["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY")
            return Blackboard(run_id=self.run_id, topic=self.topic, project_context=self.project_context)

        monkeypatch.setattr(CoordinatorAgent, "__init__", mock_init)
        monkeypatch.setattr(CoordinatorAgent, "run", mock_run)

        coord = start_run(
            topic="Test Start Run Function",
            context="Testing start_run encapsulation",
            db_path=db_file,
            env_overrides=fake_keys,
        )

        assert coord.run_id == "test_run_123"
        assert observed_env.get("ANTHROPIC_API_KEY") == "sk-ant-start-run-key-999"
        # Verify cleanup after start_run returns
        assert os.environ.get("ANTHROPIC_API_KEY") == orig_anthropic



