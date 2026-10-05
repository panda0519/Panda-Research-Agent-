"""
Diagnostic / regression tests for the Panda Research Agent.

Three tiers, cheapest/safest first:
  Tier 0 - DB-level regression tests. Read `research_runs.db` directly.
  Tier 1 - Environment / config tests.
  Tier 2 - Live adapter smoke tests.
  Tier 3 - Full pipeline smoke test with a short, realistic topic.
"""
import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("RESEARCH_DB_PATH", "research_runs.db")

BLACKBOARD_LIST_FIELDS = [
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


def _load_runs():
    if not Path(DB_PATH).exists():
        pytest.skip(f"{DB_PATH} not found -- set RESEARCH_DB_PATH to its location")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


class TestRunHistoryHealth:

    def test_db_has_at_least_one_run(self):
        rows = _load_runs()
        assert len(rows) > 0, "No runs recorded at all -- pipeline never persisted anything"

    def test_no_completed_run_is_fully_empty(self):
        rows = _load_runs()
        offenders = []
        for row in rows:
            if row["status"] != "completed":
                continue
            bb = json.loads(row["blackboard_json"])
            if all(len(bb.get(field, [])) == 0 for field in BLACKBOARD_LIST_FIELDS):
                offenders.append(row["run_id"])
        assert not offenders, (
            f"Run(s) marked 'completed' with zero output in every phase: {offenders}. "
            "Status should be 'completed_empty' (or similar) instead of 'completed' "
            "when nothing was actually produced."
        )

    def test_completed_runs_record_phase_metadata(self):
        rows = _load_runs()
        offenders = [
            row["run_id"] for row in rows
            if row["status"] == "completed"
            and json.loads(row["blackboard_json"]).get("metadata") == {}
        ]
        assert not offenders, (
            f"Completed run(s) with no phase metadata at all: {offenders}. "
            "Instrument CoordinatorAgent to record per-phase status/timing/errors."
        )

    def test_topic_length_is_sane(self, max_chars=1000):
        rows = _load_runs()
        offenders = [
            (row["run_id"], len(row["topic"]))
            for row in rows
            if len(row["topic"]) > max_chars
        ]
        assert not offenders, (
            f"Run(s) with an oversized topic field: {offenders}. "
            f"`topic` should be a short research question (<{max_chars} chars); "
            "put long background material in `project_context` instead, and "
            "validate/reject or truncate at the CLI/UI boundary."
        )

    def test_stored_counts_match_blackboard_list_lengths(self):
        rows = _load_runs()
        mismatches = []
        for row in rows:
            bb = json.loads(row["blackboard_json"])
            checks = {
                "sources_count": len(bb.get("sources", [])),
                "gaps_count": len(bb.get("gaps", [])),
                "features_count": len(bb.get("proposed_features", [])),
            }
            for col, actual in checks.items():
                if row[col] != actual:
                    mismatches.append((row["run_id"], col, row[col], actual))
        assert not mismatches, f"Column vs. blackboard mismatch: {mismatches}"


# ---------------------------------------------------------------------------
# Tier 1 -- Environment / config tests.
# ---------------------------------------------------------------------------

class TestEnvironmentConfig:

    def test_dotenv_importable(self):
        try:
            import dotenv  # noqa: F401
        except ImportError:
            pytest.fail(
                "python-dotenv is not importable. pip_install_output.txt shows it was "
                "only just installed -- if main.py calls load_dotenv() and this import "
                "used to fail, every prior run started with zero API keys in os.environ, "
                "regardless of what's in .env."
            )

    def test_load_dotenv_is_called_before_any_client(self):
        """Static check: does the entrypoint actually call load_dotenv()?"""
        entrypoint = Path(os.environ.get("ENTRYPOINT_FILE", "main.py"))
        if not entrypoint.exists():
            pytest.skip(f"{entrypoint} not found -- set ENTRYPOINT_FILE")
        text = entrypoint.read_text(encoding="utf-8", errors="ignore")
        assert "load_dotenv" in text, (
            f"{entrypoint} never calls load_dotenv() -- .env will not be read into "
            "the process environment no matter what keys are in the file."
        )

    @pytest.mark.parametrize("key,required", [
        ("ANTHROPIC_API_KEY", True),
        ("TAVILY_API_KEY", False),
        ("GEMINI_API_KEY", False),
        ("VOYAGE_API_KEY", False),
    ])
    def test_api_key_present(self, key, required):
        from dotenv import load_dotenv
        load_dotenv()
        value = os.getenv(key)
        if not required and not value:
            pytest.skip(f"{key} not set -- optional per README, that engine runs offline/mocked")
        assert value, (
            f"{key} is missing from the process environment. Every agent/adapter that "
            "depends on it will silently degrade to an empty/mock result instead of "
            "raising -- which looks exactly like what's stored in research_runs.db."
        )



# ---------------------------------------------------------------------------
# Tier 2 -- Live adapter smoke tests.
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestSearchAdapterSmoke:
    """Bypass SearchOrchestrator and every agent. Call each adapter directly
    with a trivial, guaranteed-good query, so a zero result can only mean
    the adapter itself (auth, request, or parsing) is broken."""

    QUERY = "python programming language"

    def test_anthropic_search_adapter(self):
        try:
            from search.adapters.anthropic_adapter import AnthropicSearchAdapter
        except ImportError:
            pytest.skip("AnthropicSearchAdapter module could not be imported")
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")
        adapter = AnthropicSearchAdapter()
        results = asyncio.run(adapter.search(self.QUERY))
        assert len(results) > 0, "AnthropicSearchAdapter returned nothing for a trivial query"

    def test_tavily_adapter(self):
        try:
            from search.adapters.tavily_adapter import TavilySearchAdapter as TavilyAdapter
        except ImportError:
            pytest.skip("TavilySearchAdapter module could not be imported")
        if not os.getenv("TAVILY_API_KEY"):
            pytest.skip("TAVILY_API_KEY not set")
        adapter = TavilyAdapter()
        results = asyncio.run(adapter.search(self.QUERY))
        assert len(results) > 0, "TavilyAdapter returned nothing for a trivial query"

    def test_gemini_adapter(self):
        try:
            from search.adapters.gemini_adapter import GeminiSearchAdapter as GeminiAdapter
        except ImportError:
            pytest.skip("GeminiSearchAdapter module could not be imported")
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")
        adapter = GeminiAdapter()
        if not adapter._genai:
            pytest.skip("google-generativeai package not installed")
        results = asyncio.run(adapter.search(self.QUERY))
        assert len(results) > 0, "GeminiAdapter returned nothing for a trivial query"

    def test_search_orchestrator_aggregates_at_least_one_engine(self):
        try:
            from search.orchestrator import SearchOrchestrator
        except ImportError:
            pytest.skip("SearchOrchestrator module could not be imported")
        orch = SearchOrchestrator()
        results = asyncio.run(orch.search(self.QUERY))
        assert len(results) > 0, (
            "SearchOrchestrator returned nothing even though at least one adapter "
            "should handle a trivial query -- check whether per-adapter failures are "
            "being merged into an empty list instead of raising/logging."
        )


@pytest.mark.live
class TestPaperReaderSmoke:
    def test_arxiv_lookup_returns_papers(self):
        try:
            from blackboard import Blackboard
            from message import MessageBus
            from agents.paper_reader_agent import PaperReaderAgent
        except ImportError:
            pytest.skip("PaperReaderAgent module could not be imported")
        bb = Blackboard(run_id="smoke_arxiv", topic="transformer attention mechanism")
        bus = MessageBus()
        agent = PaperReaderAgent(blackboard=bb, bus=bus)
        notes = asyncio.run(agent.fetch_arxiv("transformer attention mechanism", limit=3))
        assert len(notes) > 0, "PaperReaderAgent found zero papers for an extremely common ML topic"


@pytest.mark.live
class TestMemoryAgentSmoke:
    def test_embedding_call_succeeds(self):
        try:
            from memory.store import VoyageEmbeddingClient
        except ImportError:
            pytest.skip("VoyageEmbeddingClient module could not be imported")
        if not os.getenv("VOYAGE_API_KEY"):
            pytest.skip("VOYAGE_API_KEY not set -- MemoryAgent should be running in offline fallback")
        client = VoyageEmbeddingClient()
        vectors = client.embed_texts(["test query"])
        assert vectors is not None and len(vectors) > 0 and len(vectors[0]) > 0


# ---------------------------------------------------------------------------
# Tier 3 -- Full pipeline smoke test with a short, realistic topic.
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestFullPipelineSmoke:

    def test_short_topic_produces_nonzero_output(self):
        """Reruns the README's own quickstart topic end-to-end and checks the
        run doesn't land in the same all-zero state as run_867aa7ed."""
        try:
            from main import run_pipeline
        except ImportError:
            pytest.skip("run_pipeline entrypoint could not be imported")
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

        result = asyncio.run(
            run_pipeline(
                topic="On-device real-time speech diarization",
                context="Ultra low latency <150ms on ARM64 wearable",
            )
        )

        assert len(result.get("sources", [])) > 0, "Zero sources on a short, realistic topic"
        assert len(result.get("claim_verifications", [])) > 0, "Verification layer produced nothing"

