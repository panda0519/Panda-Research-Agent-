"""Unit tests for academic discovery in PaperReaderAgent and SurveyorAgent with TypeSafe Jev noul triage."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agents.paper_reader_agent import PaperReaderAgent
from agents.surveyor_agent import SurveyorAgent
from blackboard import Blackboard, PaperNote
from message import MessageBus
from sources.jev_client import JevClient, JevNoulDecision


def test_paper_reader_discover_and_triage_relevance_fail_open():
    bb = Blackboard(run_id="test_run_discover", topic="transformer speech diarization")
    bus = MessageBus()
    mock_jev = MagicMock(spec=JevClient)
    
    # Mock Jev noul to return below confidence threshold (0.50 < 0.75) -> fail-open
    mock_jev.noul = AsyncMock(return_value=JevNoulDecision(
        value=None,
        selected_option="RELEVANT",
        confidence=0.50,
        confidence_threshold=0.75,
        is_confident=False,
        reasoning="Low confidence decision",
        provider="jev",
        is_fallback=False,
    ))

    agent = PaperReaderAgent(
        blackboard=bb,
        bus=bus,
        jev_client=mock_jev,
    )

    p1 = PaperNote(
        title="Attention Is All You Need",
        authors=["Vaswani et al."],
        year=2017,
        url="https://arxiv.org/abs/1706.03762",
        source_api="arxiv",
        abstract="The dominant sequence transduction models...",
    )
    p2 = PaperNote(
        title="PyAnnote.audio 2.1",
        authors=["Bredin et al."],
        year=2021,
        url="https://arxiv.org/abs/2104.04045",
        source_api="arxiv",
        abstract="Neural building blocks for speaker diarization...",
    )

    agent.fetch_arxiv = AsyncMock(return_value=[p1])
    agent.fetch_semantic_scholar = AsyncMock(return_value=[p2])
    agent.fetch_core = AsyncMock(return_value=[])

    # Phase B1: discover_papers queries arXiv, Semantic Scholar, CORE concurrently
    discovered = asyncio.run(agent.discover_papers(["speech diarization"]))
    assert len(discovered) == 2
    assert {p.title for p in discovered} == {"Attention Is All You Need", "PyAnnote.audio 2.1"}

    # Phase B1.5: triage_relevance calls noul per paper, fail-open below threshold (nothing deleted)
    triaged = asyncio.run(agent.triage_relevance(discovered, topic="transformer speech diarization"))
    assert len(triaged) == 2
    assert mock_jev.noul.call_count == 2


def test_surveyor_openalex_crossref_and_unpaywall_routing():
    bb = Blackboard(run_id="test_run_surv", topic="speech diarization frameworks")
    bus = MessageBus()

    agent = SurveyorAgent(
        blackboard=bb,
        bus=bus,
    )

    agent.unpaywall.get_paper_by_doi = AsyncMock(return_value=MagicMock(is_oa=True, pdf_url="https://example.com/paper.pdf", oa_url="https://example.com/paper.html", title="Diarization Study"))

    resolved = asyncio.run(agent.route_dois_through_unpaywall(["10.1016/j.specom.2020.10.002"]))
    assert len(resolved) == 1
    assert resolved[0]["doi"] == "10.1016/j.specom.2020.10.002"
    assert resolved[0]["is_oa"] is True

