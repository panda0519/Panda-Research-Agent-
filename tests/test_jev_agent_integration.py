"""Unit tests for JevClient deterministic decision layer and agent pipeline integrations."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agents.evaluator_agent import EvaluatorAgent
from agents.gap_analyst_agent import GapAnalystAgent
from agents.grading_alignment_agent import GradingAlignmentAgent
from blackboard import Blackboard, Feature, Gap, Solution
from message import MessageBus
from sources.jev_client import (
    JevClient,
    JevDecision,
    JevScore,
    JevNoulDecision,
    decide_consensus_sync,
    decide_feasibility_sync,
    decide_gap_sync,
    decide_verdict_sync,
)
from verification.layer2_claim import Layer2ClaimVerifier


def test_jev_client_local_fallbacks():
    client = JevClient()

    # Test choice fallback
    dec = client.choice_sync("The model performance is MET according to benchmark criteria.", ["MET", "PARTIALLY_MET", "NOT_MET"])
    assert dec.value == "MET"
    assert dec.is_fallback is True

    # Test score fallback
    score = client.score_sync("Feasibility is excellent and estimated at 5.", 1, 5)
    assert score.value == 5
    assert score.is_fallback is True

    # Test noul fallback
    noul = client.noul_sync("Unrelated text", ["alpha", "beta"], confidence_threshold=0.8)
    assert noul.is_confident is False
    assert noul.value is None
    assert noul.selected_option in ["alpha", "beta"]


def test_jev_helper_routines():
    v = decide_verdict_sync("Evaluation shows all requirements are MET.", ["MET", "NOT_MET"])
    assert v.value == "MET"

    c = decide_consensus_sync("Claim is fully supported by literature evidence.", ["SUPPORTED", "REFUTED"])
    assert c.value == "SUPPORTED"

    f = decide_feasibility_sync("Feasibility rating is 4.", min_score=1, max_score=5)
    assert f.value == 4

    g = decide_gap_sync("Critical missing real-time processing pipeline.", ["critical", "minor"])
    assert g.value == "critical"


def test_grading_alignment_agent_jev_fallback():
    bb = Blackboard(run_id="run_grading", topic="voice cloning")
    bus = MessageBus()
    agent = GradingAlignmentAgent(blackboard=bb, bus=bus)

    # Force LLM generate to throw exception to trigger Jev deterministic ladder
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("LLM service unavailable")
    agent.llm = mock_llm

    rubric_text = """
    criteria:
      - criterion: "Academic Rigor"
        weight: 1.5
        description: "Examines whether academic papers and citations are documented."
      - criterion: "Technical Feasibility"
        weight: 1.0
        description: "Checks if architecture and components are realistic."
    """
    scores = asyncio.run(agent._run(rubric_input=rubric_text))
    assert len(scores) == 2
    assert scores[0].criterion == "Academic Rigor"
    assert 1.0 <= scores[0].score <= 10.0
    assert "Deterministic evaluation verdict" in scores[0].strengths
    assert len(bb.rubric_scores) == 2


def test_evaluator_agent_jev_fallback():
    bb = Blackboard(run_id="run_eval", topic="voice cloning")
    bus = MessageBus()
    bb.add_feature(
        Feature(
            feature_id="FEAT-01",
            title="Streaming Vocoder Engine",
            description="Low-latency neural vocoder running on ONNX runtime.",
            architecture_notes="Uses HiFi-GAN quantized weights.",
        )
    )

    agent = EvaluatorAgent(blackboard=bb, bus=bus)
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
    agent.llm = mock_llm

    evals = asyncio.run(agent._run())
    assert len(evals) == 1
    assert evals[0].feature_id == "FEAT-01"
    assert 1 <= evals[0].feasibility_score <= 5
    assert 1 <= evals[0].complexity_score <= 5
    assert evals[0].risk_level in ["low", "medium", "high"]
    assert len(bb.evaluations) == 1


def test_gap_analyst_agent_jev_fallback():
    bb = Blackboard(run_id="run_gaps", topic="speech synthesis")
    bus = MessageBus()
    bb.add_solution(
        Solution(
            name="Tacotron 2",
            category="open_source",
            description="Autoregressive TTS model.",
            limitations=["High inference latency", "Slow generation"],
        )
    )

    mock_openalex = MagicMock()
    mock_openalex.search_works = AsyncMock(return_value=[])
    mock_crossref = MagicMock()
    mock_crossref.search_works = AsyncMock(return_value=[])

    agent = GapAnalystAgent(
        blackboard=bb,
        bus=bus,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
    agent.llm = mock_llm

    gaps = asyncio.run(agent._run())
    assert len(gaps) >= 3
    for g in gaps:
        assert g.category in ["technical", "market", "usability", "architectural"]
        assert g.severity in ["low", "medium", "high", "critical"]
    assert len(bb.gaps) >= 3


def test_layer2_claim_verification_jev_consensus_fallback():
    bb = Blackboard(run_id="run_l2", topic="speech synthesis")
    verifier = Layer2ClaimVerifier()

    # Mock Groq and LLM to both fail
    mock_groq = AsyncMock()
    mock_groq.generate.return_value = None
    verifier.groq = mock_groq

    with patch.object(verifier.llm, "generate", side_effect=RuntimeError("Primary LLM down")):
        claim_text = "The system achieves 150ms end to end latency. Memory footprint is capped at 512MB."
        results = asyncio.run(verifier.verify_claims("AgentY", claim_text, bb))
        assert len(results) >= 1
        assert results[0].status in ["CONFIRMED", "CONTRADICTED", "NEEDS_HUMAN"]
        assert "Jev Deterministic Consensus" in results[0].rationale


def test_primary_jev_decision_paths_when_configured():
    bb = Blackboard(run_id="run_jev_primary", topic="voice cloning")
    bus = MessageBus()
    mock_jev = MagicMock(spec=JevClient)
    mock_jev.api_key = "test_typesafe_key"
    mock_jev.api_url = "https://api.typesafe.ai/v1"
    mock_jev.score_sync.return_value = JevScore(value=4, confidence=0.92, provider="jev")
    mock_jev.choice_sync.return_value = JevDecision(value="CONFIRMED", confidence=0.95, reasoning="Requirement satisfied.", provider="jev")

    # 1. GradingAlignmentAgent primary discrete scoring path
    grading_agent = GradingAlignmentAgent(blackboard=bb, bus=bus, jev_client=mock_jev)
    mock_llm = MagicMock()
    mock_llm.generate.return_value = '[{"criterion": "Latency Target", "score": 9.9, "strengths": "Ultra-low latency", "weaknesses": "None", "evidence_citations": ["GAP-01"]}]'
    grading_agent.llm = mock_llm
    rubric = "criteria:\n  - criterion: 'Latency Target'\n    weight: 1.0"
    scores = asyncio.run(grading_agent._run(rubric_input=rubric))
    assert len(scores) == 1
    assert scores[0].criterion == "Latency Target"
    assert scores[0].score == 4.0  # Jev determines discrete score (4.0) instead of LLM's 9.9
    assert scores[0].strengths == "Ultra-low latency"  # LLM rich strengths preserved

    # 2. EvaluatorAgent primary discrete scoring path
    bb.add_feature(Feature(feature_id="F1", title="Feat", description="Desc", architecture_notes="Arch"))
    eval_agent = EvaluatorAgent(blackboard=bb, bus=bus, jev_client=mock_jev)
    eval_llm = MagicMock()
    eval_llm.generate.return_value = '[{"feature_id": "F1", "feasibility_score": 1, "complexity_score": 1, "risk_level": "low", "risks": ["Cold start latency"], "mitigations": ["Pre-warming"], "overall_assessment": "Solid design"}]'
    eval_agent.llm = eval_llm
    evals = asyncio.run(eval_agent._run())
    assert len(evals) == 1
    assert evals[0].feature_id == "F1"
    assert evals[0].feasibility_score == 4  # Jev determines discrete score (4) instead of LLM's 1
    assert evals[0].risks == ["Cold start latency"]  # LLM rich qualitative analysis preserved

    # 3. GapAnalystAgent primary discrete classification path
    gap_agent = GapAnalystAgent(blackboard=bb, bus=bus, jev_client=mock_jev)
    gap_llm = MagicMock()
    gap_llm.generate.return_value = '[{"gap_id": "GAP-01", "category": "market", "title": "Edge Memory Cap", "description": "Memory footprint exceeds 256MB on mobile.", "evidence": ["Paper 1"], "severity": "low"}]'
    gap_agent.llm = gap_llm
    mock_jev.choice_sync.return_value = JevDecision(value="critical", confidence=0.95, reasoning="Critical bottleneck", provider="jev")
    gaps = asyncio.run(gap_agent._run())
    assert len(gaps) == 1
    assert gaps[0].gap_id == "GAP-01"
    assert gaps[0].severity == "critical"  # Jev determines discrete severity (critical) instead of LLM's low
    assert gaps[0].title == "Edge Memory Cap"  # LLM domain gap title preserved

    # 4. Layer2ClaimVerifier primary discrete consensus path
    verifier = Layer2ClaimVerifier(jev_client=mock_jev)
    verifier.llm = mock_llm
    mock_groq = AsyncMock()
    mock_groq.api_key = "test_groq_key"
    mock_groq.generate.return_value = '[{"claim_text": "System runs in under 100ms on client devices.", "status": "UNSUPPORTED", "cited_urls": ["https://arxiv.org/abs/1"]}]'
    verifier.groq = mock_groq
    mock_jev.choice_sync.return_value = JevDecision(value="CONFIRMED", confidence=0.98, reasoning="Fully corroborated by benchmarks", provider="jev")
    claim_verifs = asyncio.run(verifier.verify_claims("AgentX", "System runs in under 100ms on client devices.", bb))
    assert len(claim_verifs) == 1
    assert claim_verifs[0].status == "CONFIRMED"  # Jev determines consensus status (CONFIRMED) instead of LLM's UNSUPPORTED
    assert claim_verifs[0].claim_text == "System runs in under 100ms on client devices."  # LLM extracted claim preserved
    assert bb.metadata["second_model_used"].startswith("TypeSafe Jev Primary")

