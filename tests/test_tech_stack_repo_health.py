"""Unit tests for TechStackAgent GitHub repo health enrichment and fallback ladder."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agents.tech_stack_agent import TechStackAgent
from agents.reporter_agent import ReporterAgent
from blackboard import Blackboard, Feature
from message import MessageBus
from sources.github_client import GitHubClient, GitHubRepoHealth


def _create_mock_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = """[
        {
            "layer": "ai_orchestration",
            "selected_tech": "pyannote/pyannote-audio",
            "alternatives_considered": ["speechbrain", "kaldi"],
            "rationale": "State of the art diarization pipeline."
        },
        {
            "layer": "backend",
            "selected_tech": "FastAPI",
            "alternatives_considered": ["Flask", "Django"],
            "rationale": "High throughput async server."
        }
    ]"""
    return mock_llm


def test_tech_stack_repo_health_enrichment():
    bb = Blackboard(run_id="run_ts_1", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm()
    mock_gh = MagicMock(spec=GitHubClient)

    # Mock response for pyannote/pyannote-audio
    health_pyannote = GitHubRepoHealth(
        owner="pyannote",
        repo="pyannote-audio",
        full_name="pyannote/pyannote-audio",
        stars=5500,
        forks=700,
        open_issues=50,
        license_spdx="MIT",
        is_archived=False,
        is_authenticated=True,
    )
    # Mock response for FastAPI search
    health_fastapi = GitHubRepoHealth(
        owner="fastapi",
        repo="fastapi",
        full_name="fastapi/fastapi",
        stars=75000,
        forks=6000,
        open_issues=200,
        license_spdx="MIT",
        is_archived=False,
    )

    async def mock_get_repo(owner, repo):
        if owner == "pyannote" and repo == "pyannote-audio":
            return health_pyannote
        return None

    async def mock_search(query, limit=1):
        if "fastapi" in query.lower():
            return [health_fastapi]
        return []

    mock_gh.get_repo_health = AsyncMock(side_effect=mock_get_repo)
    mock_gh.search_repositories = AsyncMock(side_effect=mock_search)

    agent = TechStackAgent(blackboard=bb, bus=bus, llm_client=mock_llm, github_client=mock_gh)
    recs = asyncio.run(agent._run())

    assert len(recs) == 2
    rec1 = recs[0]
    assert rec1.selected_tech == "pyannote/pyannote-audio"
    assert rec1.stars == 5500
    assert rec1.forks == 700
    assert rec1.license == "MIT"
    assert rec1.is_archived is False
    assert "5,500 stars" in (rec1.health_notes or "")

    rec2 = recs[1]
    assert rec2.selected_tech == "FastAPI"
    assert rec2.stars == 75000
    assert rec2.repo_url == "https://github.com/fastapi/fastapi"

    # Check reporter agent renders health notes
    reporter = ReporterAgent(blackboard=bb, bus=bus)
    report = reporter.generate_report()
    assert "GitHub Health:" in report
    assert "5,500 stars" in report


def test_tech_stack_archived_repo_warning():
    bb = Blackboard(run_id="run_ts_2", topic="legacy ML")
    bus = MessageBus()
    mock_llm = MagicMock()
    mock_llm.generate.return_value = """[
        {
            "layer": "backend",
            "selected_tech": "theano/Theano",
            "alternatives_considered": ["PyTorch", "TensorFlow"],
            "rationale": "Legacy computation engine."
        }
    ]"""
    mock_gh = MagicMock(spec=GitHubClient)
    archived_health = GitHubRepoHealth(
        owner="theano",
        repo="Theano",
        full_name="theano/Theano",
        stars=9000,
        forks=2500,
        open_issues=120,
        license_spdx="BSD-3-Clause",
        is_archived=True,
    )
    mock_gh.get_repo_health = AsyncMock(return_value=archived_health)

    agent = TechStackAgent(blackboard=bb, bus=bus, llm_client=mock_llm, github_client=mock_gh)
    recs = asyncio.run(agent._run())

    assert len(recs) == 1
    assert recs[0].is_archived is True
    assert "⚠️ Repository is archived on GitHub" in recs[0].health_notes


def test_tech_stack_github_error_graceful_fallback():
    bb = Blackboard(run_id="run_ts_3", topic="speech diarization")
    bus = MessageBus()
    mock_llm = _create_mock_llm()
    mock_gh = MagicMock(spec=GitHubClient)

    # GitHub network timeout or 404
    mock_gh.get_repo_health = AsyncMock(side_effect=Exception("Network error"))
    mock_gh.search_repositories = AsyncMock(side_effect=Exception("Network error"))

    agent = TechStackAgent(blackboard=bb, bus=bus, llm_client=mock_llm, github_client=mock_gh)
    recs = asyncio.run(agent._run())

    # Agent still completes and generates recommendations without GitHub stats
    assert len(recs) == 2
    assert recs[0].stars is None
    assert recs[0].health_notes is None
