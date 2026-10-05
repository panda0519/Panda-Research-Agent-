"""Unit tests for SurveyorAgent and GapAnalystAgent broader academic discovery ladder (OpenAlex -> Crossref -> Baseline)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from agents.gap_analyst_agent import GapAnalystAgent
from agents.surveyor_agent import SurveyorAgent
from blackboard import Blackboard, Gap, Solution
from message import MessageBus
from sources.crossref_client import CrossrefClient, CrossrefWork
from sources.openalex_client import OpenAlexClient, OpenAlexWork


def _create_mock_llm(json_response: str):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json_response
    return mock_llm


def test_surveyor_agent_openalex_primary_discovery():
    bb = Blackboard(run_id="run_surv_1", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm("""[
        {
            "name": "PyAnnote Audio",
            "category": "open_source",
            "description": "Neural diarization toolkit based on PyTorch.",
            "strengths": ["End-to-end neural", "Pre-trained models"],
            "limitations": ["High GPU memory demand"],
            "sources": ["https://openalex.org/W12345"]
        }
    ]""")

    mock_openalex = MagicMock(spec=OpenAlexClient)
    mock_crossref = MagicMock(spec=CrossrefClient)

    oa_work = OpenAlexWork(
        id="https://openalex.org/W12345",
        doi="https://doi.org/10.1016/j.specom.2020.10.002",
        title="PyAnnote.audio: neural building blocks for speaker diarization",
        publication_year=2020,
        cited_by_count=450,
        concepts=["Speaker Diarization", "Speech Recognition"],
        primary_location_url="https://openalex.org/W12345",
    )
    mock_openalex.search_works = AsyncMock(return_value=[oa_work])
    mock_crossref.search_works = AsyncMock(return_value=[])

    agent = SurveyorAgent(
        blackboard=bb,
        bus=bus,
        llm_client=mock_llm,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )

    solutions = asyncio.run(agent._run())

    assert len(solutions) == 1
    assert solutions[0].name == "PyAnnote Audio"
    assert mock_openalex.search_works.call_count == 1
    assert mock_crossref.search_works.call_count == 0  # Backup skipped when primary succeeds

    # Verify OpenAlex context was passed to prompt
    prompt_arg = mock_llm.generate.call_args[1]["prompt"]
    assert "BROADER ACADEMIC DISCOVERY (OpenAlex / Crossref):" in prompt_arg
    assert "[OpenAlex] PyAnnote.audio" in prompt_arg
    assert "450 citations" in prompt_arg


def test_surveyor_agent_crossref_backup_discovery():
    bb = Blackboard(run_id="run_surv_2", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm("""[
        {
            "name": "Kaldi Diarization",
            "category": "open_source",
            "description": "Classic HMM-GMM / x-vector diarization recipe.",
            "strengths": ["Well established", "Low resource"],
            "limitations": ["Complex setup"],
            "sources": []
        }
    ]""")

    mock_openalex = MagicMock(spec=OpenAlexClient)
    mock_crossref = MagicMock(spec=CrossrefClient)

    # OpenAlex fails/empty
    mock_openalex.search_works = AsyncMock(return_value=[])
    # Crossref returns item
    cr_work = CrossrefWork(
        doi="10.1109/ICASSP.2018.8461633",
        title="X-Vectors: Robust DNN Embeddings for Speaker Recognition",
        authors=["David Snyder", "Daniel Garcia-Romero"],
        year=2018,
        is_referenced_by_count=1200,
        url="https://doi.org/10.1109/ICASSP.2018.8461633",
    )
    mock_crossref.search_works = AsyncMock(return_value=[cr_work])

    agent = SurveyorAgent(
        blackboard=bb,
        bus=bus,
        llm_client=mock_llm,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )

    solutions = asyncio.run(agent._run())

    assert len(solutions) == 1
    assert mock_openalex.search_works.call_count == 1
    assert mock_crossref.search_works.call_count == 1

    prompt_arg = mock_llm.generate.call_args[1]["prompt"]
    assert "[Crossref] X-Vectors: Robust DNN Embeddings" in prompt_arg
    assert "1200 citations" in prompt_arg


def test_surveyor_agent_baseline_fallback():
    bb = Blackboard(run_id="run_surv_3", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm("""[
        {
            "name": "Baseline Diarizer",
            "category": "open_source",
            "description": "Fallback system description.",
            "strengths": ["Simple"],
            "limitations": ["Basic"],
            "sources": []
        }
    ]""")

    mock_openalex = MagicMock(spec=OpenAlexClient)
    mock_crossref = MagicMock(spec=CrossrefClient)

    # Both fail with exceptions
    mock_openalex.search_works = AsyncMock(side_effect=Exception("OpenAlex timeout"))
    mock_crossref.search_works = AsyncMock(side_effect=Exception("Crossref 503"))

    agent = SurveyorAgent(
        blackboard=bb,
        bus=bus,
        llm_client=mock_llm,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )

    solutions = asyncio.run(agent._run())

    assert len(solutions) == 1
    assert solutions[0].name == "Baseline Diarizer"


def test_gap_analyst_agent_openalex_primary_discovery():
    bb = Blackboard(run_id="run_gap_1", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm("""[
        {
            "gap_id": "GAP-01",
            "category": "technical",
            "title": "Overlapping Speech Inaccuracy",
            "description": "High diarization error rate during speaker overlaps.",
            "evidence": ["OpenAlex study highlights overlap degradation."],
            "severity": "critical"
        }
    ]""")

    mock_openalex = MagicMock(spec=OpenAlexClient)
    mock_crossref = MagicMock(spec=CrossrefClient)

    oa_work = OpenAlexWork(
        id="https://openalex.org/W9988",
        doi="https://doi.org/10.1016/j.csl.2021.101290",
        title="Handling Overlapping Speech in Speaker Diarization: A Systematic Review",
        publication_year=2021,
        abstract="Current diarization systems suffer a 40% error rate increase on overlapping speech segments.",
    )
    mock_openalex.search_works = AsyncMock(return_value=[oa_work])
    mock_crossref.search_works = AsyncMock(return_value=[])

    agent = GapAnalystAgent(
        blackboard=bb,
        bus=bus,
        llm_client=mock_llm,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )

    gaps = asyncio.run(agent._run())

    assert len(gaps) == 1
    assert gaps[0].gap_id == "GAP-01"
    assert gaps[0].severity == "critical"
    assert mock_openalex.search_works.call_count == 1
    assert mock_crossref.search_works.call_count == 0

    prompt_arg = mock_llm.generate.call_args[1]["prompt"]
    assert "ACADEMIC LITERATURE EVIDENCE & BOTTLENECKS:" in prompt_arg
    assert "[OpenAlex] Handling Overlapping Speech in Speaker Diarization" in prompt_arg
    assert "40% error rate increase" in prompt_arg


def test_gap_analyst_agent_crossref_backup_discovery():
    bb = Blackboard(run_id="run_gap_2", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm("""[
        {
            "gap_id": "GAP-02",
            "category": "architectural",
            "title": "Streaming Latency Bottleneck",
            "description": "Non-causal clustering prevents real-time processing.",
            "evidence": ["Crossref survey on low-latency clustering."],
            "severity": "high"
        }
    ]""")

    mock_openalex = MagicMock(spec=OpenAlexClient)
    mock_crossref = MagicMock(spec=CrossrefClient)

    mock_openalex.search_works = AsyncMock(return_value=[])
    cr_work = CrossrefWork(
        doi="10.1109/TASLP.2022.1001",
        title="Streaming Speaker Diarization Challenges under Low-Latency Constraints",
        year=2022,
        abstract="Offline spectral clustering requires the entire audio recording and cannot operate in online mode.",
    )
    mock_crossref.search_works = AsyncMock(return_value=[cr_work])

    agent = GapAnalystAgent(
        blackboard=bb,
        bus=bus,
        llm_client=mock_llm,
        openalex_client=mock_openalex,
        crossref_client=mock_crossref,
    )

    gaps = asyncio.run(agent._run())

    assert len(gaps) == 1
    assert gaps[0].gap_id == "GAP-02"
    assert mock_openalex.search_works.call_count == 1
    assert mock_crossref.search_works.call_count == 1

    prompt_arg = mock_llm.generate.call_args[1]["prompt"]
    assert "[Crossref] Streaming Speaker Diarization Challenges" in prompt_arg
