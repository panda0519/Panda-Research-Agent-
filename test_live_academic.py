"""Live academic literature integration test.
Validates that arXiv and Semantic Scholar APIs return parseable results.
"""
import asyncio
import sys
import os
import logging
import pytest

logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

sys.path.insert(0, os.path.dirname(__file__))

from blackboard import Blackboard
from message import MessageBus
from agents.paper_reader_agent import PaperReaderAgent


@pytest.mark.live
def test_live_arxiv():
    async def _test():
        bb = Blackboard(run_id="live_test_arxiv", topic="speech diarization")
        bus = MessageBus()
        agent = PaperReaderAgent(blackboard=bb, bus=bus)

        print("[1/3] Testing live arXiv query...")
        notes = await agent.fetch_arxiv("speech diarization", limit=3)
        print(f"  arXiv returned {len(notes)} papers")
        for n in notes:
            print(f"    - {n.title} ({n.year}) [{n.source_api}]")
            assert n.title, "Paper must have a title"
            assert n.url, "Paper must have a URL"
        print("  [OK] arXiv\n")
        return notes
    return asyncio.run(_test())


@pytest.mark.live
def test_live_semantic_scholar():
    async def _test():
        bb = Blackboard(run_id="live_test_s2", topic="speech diarization")
        bus = MessageBus()
        agent = PaperReaderAgent(blackboard=bb, bus=bus)

        print("[2/3] Testing live Semantic Scholar query...")
        notes = await agent.fetch_semantic_scholar("speech diarization", limit=3)
        print(f"  Semantic Scholar returned {len(notes)} papers")
        for n in notes:
            print(f"    - {n.title} ({n.year}) [{n.source_api}]")
            assert n.title, "Paper must have a title"
            assert n.url, "Paper must have a URL"
        print("  [OK] Semantic Scholar\n")
        return notes
    return asyncio.run(_test())


@pytest.mark.live
def test_full_paper_reader_pipeline():
    async def _test():
        bb = Blackboard(run_id="live_test_full", topic="speech diarization")
        bus = MessageBus()
        agent = PaperReaderAgent(blackboard=bb, bus=bus)

        print("[3/3] Testing full PaperReaderAgent pipeline (arXiv + S2, dedup)...")
        papers = await agent.run(max_papers=5)
        print(f"  PaperReaderAgent produced {len(papers)} papers on Blackboard")
        for p in papers:
            print(f"    - [{p.source_api}] {p.title}")
        assert len(papers) > 0, "Expected at least 1 paper from live APIs"
        print(f"  [OK] PaperReaderAgent pipeline ({len(papers)} papers)\n")
    return asyncio.run(_test())


def main():
    print("=" * 60)
    print("  LIVE ACADEMIC LITERATURE INTEGRATION TEST")
    print("=" * 60 + "\n")

    arxiv_notes = []
    s2_notes = []

    try:
        arxiv_notes = test_live_arxiv()
    except Exception as e:
        print(f"  [WARN] arXiv test failed: {e}\n")

    try:
        s2_notes = test_live_semantic_scholar()
    except Exception as e:
        print(f"  [WARN] Semantic Scholar test failed: {e}\n")

    if arxiv_notes or s2_notes:
        try:
            test_full_paper_reader_pipeline()
        except Exception as e:
            print(f"  [WARN] Full pipeline test failed: {e}\n")
    else:
        print("  Skipping full pipeline test (no papers from live APIs)\n")

    print("=" * 60)
    print("  TEST SUITE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()