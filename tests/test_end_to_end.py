import asyncio
import tempfile
from pathlib import Path
from agents.coordinator_agent import CoordinatorAgent
from storage.db import get_run, list_runs
from blackboard import Source, PaperNote


def test_full_pipeline_mock_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = f"{tmpdir}/test_runs.db"
        rubric_file = f"{tmpdir}/test_rubric.yaml"
        Path(rubric_file).write_text(
            """
criteria:
  - criterion: "Depth of Literature"
    weight: 0.5
  - criterion: "Feasibility of Architecture"
    weight: 0.5
""",
            encoding="utf-8",
        )

        coordinator = CoordinatorAgent(
            topic="Streaming on-device speech diarization",
            project_context="Targeting ultra-low latency <150ms on ARM64 wearable device.",
            db_path=db_file,
        )

        def mock_generate(prompt, **kwargs):
            if "Extract up to 5 key atomic factual claims" in prompt:
                return '[{"claim_text": "PyAnnote achieves 5% DER on DIHARD III", "cited_urls": ["https://arxiv.org/abs/2101.0001"], "status": "CONFIRMED", "rationale": "Directly backed by paper abstract."}]'
            if "grading / evaluation criteria" in prompt or "Score the research artifacts against each criterion" in prompt:
                return '[{"criterion": "Depth of Literature", "weight": 0.5, "score": 9.0, "strengths": "Cites recent arXiv papers", "weaknesses": "None", "evidence_citations": ["GAP-01"]}, {"criterion": "Feasibility of Architecture", "weight": 0.5, "score": 8.5, "strengths": "Clear ARM64 consideration", "weaknesses": "None", "evidence_citations": ["FEAT-01"]}]'
            if "Extract 3 to 6 prominent existing solutions" in prompt:
                return '[{"name": "PyAnnote Audio", "category": "open_source", "description": "State of the art neural speaker diarization toolkit.", "strengths": ["High accuracy", "Modular"], "limitations": ["Batch oriented", "High memory footprint"], "sources": ["https://arxiv.org/abs/2101.0001"]}]'
            if "Identify 3 to 5 critical gaps" in prompt:
                return '[{"gap_id": "GAP-01", "category": "technical", "title": "High Latency in Streaming Diarization", "description": "Existing models require >5s audio buffers, making real-time streaming infeasible.", "evidence": ["PyAnnote limitations"], "severity": "critical"}]'
            if "Design 3 to 5 high-impact, novel features" in prompt:
                return '[{"feature_id": "FEAT-01", "title": "Chunked Causal SincNet with Recurrent Memory", "description": "Streaming audio encoder operating on 100ms frames with temporal attention cache.", "target_gap_ids": ["GAP-01"], "architecture_notes": "Quantized INT8 ONNX graph with NEON SIMD acceleration.", "novelty_rationale": "Reduces end-to-end latency from 5000ms to 85ms."}]'
            if "Recommend a practical, modern technology stack" in prompt:
                return '[{"layer": "ai_orchestration", "selected_tech": "ONNX Runtime with ARM NN Execution Provider", "alternatives_considered": ["PyTorch Mobile", "TFLite"], "rationale": "Optimized SIMD acceleration on ARM64."}]'
            if "Evaluate the following proposed features" in prompt:
                return '[{"feature_id": "FEAT-01", "feasibility_score": 4, "complexity_score": 4, "risk_level": "medium", "risks": ["Cache invalidation under fast speaker turn-taking"], "mitigations": ["Dynamic threshold hysteresis"], "overall_assessment": "Highly viable with standard ONNX tooling."}]'
            if "Examine the synthesized findings from different agents for contradictions" in prompt:
                return '[]'
            return "General response"

        # Attach mock LLM to coordinator and sub-agents
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

        # Mock OpenAlex, Crossref, and GitHub calls to avoid live network latency
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

        bb = asyncio.run(coordinator.run(rubric_path=rubric_file))

        assert len(bb.sources) >= 1
        assert len(bb.paper_notes) >= 1
        assert len(bb.existing_solutions) >= 1
        assert len(bb.gaps) >= 1
        assert len(bb.proposed_features) >= 1
        assert len(bb.tech_stack) >= 1
        assert len(bb.evaluations) >= 1
        assert len(bb.claim_verifications) >= 1
        assert len(bb.rubric_scores) == 2
        assert len(bb.report_markdown) > 500

        saved = get_run(coordinator.run_id, db_path=db_file)
        assert saved is not None
        assert saved["status"] == "completed"
        assert saved["topic"] == "Streaming on-device speech diarization"
        assert saved["gaps_count"] >= 1
        assert saved["features_count"] >= 1

        recent_runs = list_runs(db_path=db_file)
        assert len(recent_runs) == 1


def test_sqlite_blackboard_new_fields_round_trip():
    """Explicitly verify that all new Blackboard fields from Phases A-E survive SQLite serialization and deserialization."""
    from storage.db import save_run
    from blackboard import Blackboard, PaperNote, TechStackRecommendation, ClaimVerification, Solution, Gap, Feature, Evaluation, RubricScoreItem

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = f"{tmpdir}/test_roundtrip.db"
        bb = Blackboard(
            run_id="run_test_fields_123",
            topic="Streaming audio models",
            project_context="ARM64 deployment",
        )

        # Populate with specialized fields
        bb.add_paper_note(
            PaperNote(
                title="Neural Diarization",
                authors=["Jane Doe"],
                year=2024,
                url="https://doi.org/10.1234/test",
                source_api="arxiv",
                abstract="Test abstract",
                is_open_access=True,
                oa_source="unpaywall",
                full_text_url="https://example.com/paper.pdf",
            )
        )
        bb.add_tech_stack_item(
            TechStackRecommendation(
                layer="ai_inference",
                selected_tech="ONNX Runtime",
                repo_url="https://github.com/microsoft/onnxruntime",
                health_notes="GitHub Health: 35000 stars, 6000 forks, active",
                is_archived=False,
                alternatives_considered=["TFLite"],
                rationale="Optimized NEON execution",
            )
        )
        bb.add_solution(
            Solution(
                name="PyAnnote",
                category="open_source",
                description="Speaker diarization",
                sources=["https://openalex.org/W12345", "https://doi.org/10.1016/j.specom.2020.10.002"],
            )
        )
        bb.add_gap(
            Gap(
                gap_id="GAP-01",
                category="technical",
                title="High Latency",
                description="Buffer latency > 5s",
                evidence=["Crossref benchmark survey (2022)", "OpenAlex study"],
                severity="critical",
            )
        )
        bb.add_claim_verification(
            ClaimVerification(
                claim_text="ONNX Runtime executes INT8 graph in <50ms",
                source_agent="TechStackAgent",
                cited_urls=["https://github.com/microsoft/onnxruntime"],
                status="CONFIRMED",
                single_engine=True,
                rationale="[Deterministic Compute Verified: Arithmetic] 200ms -> 50ms (75% reduction)",
            )
        )

        # Save to SQLite
        save_run(bb, status="completed", db_path=db_file)

        # Retrieve and parse
        row = get_run("run_test_fields_123", db_path=db_file)
        assert row is not None
        assert row["status"] == "completed"

        loaded_bb = Blackboard.from_json(row["blackboard_json"])

        # Validate PaperNote fields
        assert len(loaded_bb.paper_notes) == 1
        p = loaded_bb.paper_notes[0]
        assert p.is_open_access is True
        assert p.oa_source == "unpaywall"
        assert p.full_text_url == "https://example.com/paper.pdf"

        # Validate TechStackRecommendation fields
        assert len(loaded_bb.tech_stack) == 1
        ts = loaded_bb.tech_stack[0]
        assert ts.repo_url == "https://github.com/microsoft/onnxruntime"
        assert "35000 stars" in ts.health_notes
        assert ts.is_archived is False

        # Validate Solution sources
        assert len(loaded_bb.existing_solutions) == 1
        sol = loaded_bb.existing_solutions[0]
        assert len(sol.sources) == 2
        assert "https://openalex.org/W12345" in sol.sources

        # Validate Gap evidence
        assert len(loaded_bb.gaps) == 1
        g = loaded_bb.gaps[0]
        assert len(g.evidence) == 2
        assert "OpenAlex study" in g.evidence

        # Validate ClaimVerification fields
        assert len(loaded_bb.claim_verifications) == 1
        cv = loaded_bb.claim_verifications[0]
        assert cv.single_engine is True
        assert "[Deterministic Compute Verified: Arithmetic]" in cv.rationale

