"""Unit tests for PaperReaderAgent Open Access resolution ladder (Unpaywall -> CORE -> Baseline)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from agents.paper_reader_agent import PaperReaderAgent
from agents.reporter_agent import ReporterAgent
from blackboard import Blackboard, PaperNote
from message import MessageBus
from sources.core_client import CoreClient, CorePaper
from sources.unpaywall_client import UnpaywallClient, UnpaywallPaper


SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query: search_query=all:diarization</title>
  <entry>
    <id>http://arxiv.org/abs/2305.12345v1</id>
    <published>2023-05-18T12:00:00Z</published>
    <title> Neural Speech Diarization with Transformers </title>
    <summary> We propose an end-to-end neural diarization method achieving 5% DER. </summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <arxiv:doi>10.48550/arXiv.2305.12345</arxiv:doi>
  </entry>
</feed>
"""

SAMPLE_S2_DATA = {
    "data": [
        {
            "paperId": "s2_doc_1",
            "title": "A Review of Speaker Diarization",
            "abstract": "Comprehensive survey on speaker diarization techniques.",
            "year": 2021,
            "url": "https://www.semanticscholar.org/paper/s2_doc_1",
            "venue": "Speech Communication",
            "authors": [{"name": "Hervé Bredin"}],
            "externalIds": {"DOI": "10.1016/j.specom.2020.10.002"},
        },
        {
            "paperId": "s2_doc_2",
            "title": "Closed Access Paper",
            "abstract": "Proprietary algorithm behind paywall.",
            "year": 2020,
            "url": "https://www.semanticscholar.org/paper/s2_doc_2",
            "venue": "IEEE TASLP",
            "authors": [{"name": "John Doe"}],
            "externalIds": {"DOI": "10.1109/closed.2020.01"},
        },
    ]
}


def test_arxiv_open_access_pdf_resolution():
    bb = Blackboard(run_id="run_oa_1", topic="speech diarization")
    bus = MessageBus()
    agent = PaperReaderAgent(blackboard=bb, bus=bus)

    notes = agent.parse_arxiv_atom(SAMPLE_ARXIV_XML)
    assert len(notes) == 1
    note = notes[0]
    assert note.is_open_access is True
    assert note.oa_source == "arxiv"
    assert note.full_text_url == "http://arxiv.org/pdf/2305.12345v1.pdf"
    assert note.doi == "10.48550/arXiv.2305.12345"


def test_unpaywall_primary_resolution():
    bb = Blackboard(run_id="run_oa_2", topic="speech diarization")
    bus = MessageBus()

    mock_unpaywall = MagicMock(spec=UnpaywallClient)
    mock_core = MagicMock(spec=CoreClient)

    # Unpaywall returns OA PDF
    mock_unpaywall.get_paper_by_doi = AsyncMock(
        return_value=UnpaywallPaper(
            doi="10.1016/j.specom.2020.10.002",
            is_oa=True,
            pdf_url="https://sciencedirect.com/article/pii/specom2020.pdf",
        )
    )
    mock_core.get_work_by_doi = AsyncMock(return_value=None)

    agent = PaperReaderAgent(
        blackboard=bb,
        bus=bus,
        unpaywall_client=mock_unpaywall,
        core_client=mock_core,
    )

    paper = PaperNote(
        title="A Review of Speaker Diarization",
        authors=["Hervé Bredin"],
        year=2021,
        url="https://doi.org/10.1016/j.specom.2020.10.002",
        source_api="semantic_scholar",
        abstract="Comprehensive survey.",
        doi="10.1016/j.specom.2020.10.002",
    )

    asyncio.run(agent._resolve_open_access(paper))

    assert paper.is_open_access is True
    assert paper.oa_source == "unpaywall"
    assert paper.full_text_url == "https://sciencedirect.com/article/pii/specom2020.pdf"
    assert mock_core.get_work_by_doi.call_count == 0  # Backup not invoked when Unpaywall succeeds


def test_core_backup_resolution_when_unpaywall_fails():
    bb = Blackboard(run_id="run_oa_3", topic="speech diarization")
    bus = MessageBus()

    mock_unpaywall = MagicMock(spec=UnpaywallClient)
    mock_core = MagicMock(spec=CoreClient)

    # Unpaywall misses
    mock_unpaywall.get_paper_by_doi = AsyncMock(return_value=None)
    # CORE succeeds
    mock_core.get_work_by_doi = AsyncMock(
        return_value=CorePaper(
            core_id="core_9988",
            doi="10.1016/j.specom.2020.10.002",
            title="A Review of Speaker Diarization",
            download_url="https://core.ac.uk/download/pdf/core_9988.pdf",
        )
    )

    agent = PaperReaderAgent(
        blackboard=bb,
        bus=bus,
        unpaywall_client=mock_unpaywall,
        core_client=mock_core,
    )

    paper = PaperNote(
        title="A Review of Speaker Diarization",
        authors=["Hervé Bredin"],
        year=2021,
        url="https://doi.org/10.1016/j.specom.2020.10.002",
        source_api="semantic_scholar",
        abstract="Comprehensive survey.",
        doi="10.1016/j.specom.2020.10.002",
    )

    asyncio.run(agent._resolve_open_access(paper))

    assert paper.is_open_access is True
    assert paper.oa_source == "core"
    assert paper.full_text_url == "https://core.ac.uk/download/pdf/core_9988.pdf"


def test_baseline_fallback_when_both_fail():
    bb = Blackboard(run_id="run_oa_4", topic="closed science")
    bus = MessageBus()

    mock_unpaywall = MagicMock(spec=UnpaywallClient)
    mock_core = MagicMock(spec=CoreClient)

    # Both fail
    mock_unpaywall.get_paper_by_doi = AsyncMock(return_value=None)
    mock_core.get_work_by_doi = AsyncMock(return_value=None)
    mock_core.search_works = AsyncMock(return_value=[])

    agent = PaperReaderAgent(
        blackboard=bb,
        bus=bus,
        unpaywall_client=mock_unpaywall,
        core_client=mock_core,
    )

    paper = PaperNote(
        title="Closed Access Paper",
        authors=["John Doe"],
        year=2020,
        url="https://doi.org/10.1109/closed.2020.01",
        source_api="semantic_scholar",
        abstract="Closed paper abstract.",
        doi="10.1109/closed.2020.01",
    )

    asyncio.run(agent._resolve_open_access(paper))

    assert paper.is_open_access is False
    assert paper.full_text_url is None
    assert paper.oa_source is None


def test_reporter_agent_renders_oa_badge():
    bb = Blackboard(run_id="run_oa_5", topic="speech diarization")
    bus = MessageBus()

    paper = PaperNote(
        title="Neural Diarization",
        authors=["Alice Smith"],
        year=2023,
        url="https://arxiv.org/abs/2305.12345",
        source_api="arxiv",
        abstract="Neural diarization.",
        is_open_access=True,
        full_text_url="https://arxiv.org/pdf/2305.12345.pdf",
        oa_source="arxiv",
    )
    bb.add_paper_note(paper)

    reporter = ReporterAgent(blackboard=bb, bus=bus)
    report = reporter.generate_report()
    assert "Open Access:" in report
    assert "[Full Text PDF](https://arxiv.org/pdf/2305.12345.pdf)" in report
    assert "(`arxiv`)" in report
