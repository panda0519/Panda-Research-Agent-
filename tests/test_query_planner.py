import asyncio
from blackboard import Blackboard
from message import MessageBus
from agents.query_planner_agent import QueryPlannerAgent


def test_query_planner_decomposition_heuristic():
    bb = Blackboard(
        run_id="test_qp_1",
        topic="Dragon Hatchling BDH: Baby Dragon Hatchling and emerging AI architectures for real-time edge processing",
        project_context="Targeting ultra-low compute edge microcontroller devices.",
    )
    bus = MessageBus()
    agent = QueryPlannerAgent(blackboard=bb, bus=bus)

    # Run deterministic fallback
    plan = agent._build_deterministic_plan(bb.topic, bb.project_context)

    assert "canonical_topic" in plan
    assert "web_queries" in plan
    assert "academic_queries" in plan
    assert len(plan["web_queries"]) >= 4
    assert len(plan["academic_queries"]) >= 4

    # Ensure academic queries are short keyword phrases without punctuation
    for q in plan["academic_queries"]:
        words = q.split()
        assert len(words) <= 6
        assert "?" not in q
        assert ":" not in q


def test_query_planner_run_phase():
    bb = Blackboard(run_id="test_qp_2", topic="On-device real-time speech diarization")
    bus = MessageBus()
    agent = QueryPlannerAgent(blackboard=bb, bus=bus)

    # Mock LLM response
    def mock_generate(prompt, **kwargs):
        return """{
            "canonical_topic": "On-Device Real-Time Speech Diarization",
            "domain_taxonomy": ["Speech Processing", "Edge AI", "Neural Acoustic Modeling"],
            "core_challenges": ["Buffer latency reduction", "Quantization degradation"],
            "web_queries": ["streaming speech diarization onnx github", "real time diarization benchmark 2024"],
            "academic_queries": ["neural speech diarization", "streaming speaker diarization"]
        }"""

    agent.llm.generate = mock_generate

    result = asyncio.run(agent.run_phase())
    assert result["canonical_topic"] == "On-Device Real-Time Speech Diarization"
    assert len(result["web_queries"]) == 2
    assert len(result["academic_queries"]) == 2
    assert "query_plan" in bb.metadata
    assert bb.metadata["canonical_topic"] == "On-Device Real-Time Speech Diarization"
