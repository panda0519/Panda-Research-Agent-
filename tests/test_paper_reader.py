import asyncio
from blackboard import Blackboard
from message import MessageBus
from agents.paper_reader_agent import PaperReaderAgent


SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=all:diarization</title>
  <entry>
    <id>http://arxiv.org/abs/2305.12345v1</id>
    <published>2023-05-18T12:00:00Z</published>
    <title> Neural Speech Diarization with Transformers </title>
    <summary> We propose an end-to-end neural diarization method achieving 5% DER. </summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
  </entry>
</feed>
"""

SAMPLE_S2_JSON = {
    "data": [
        {
            "paperId": "abc123456",
            "title": "On-Device Diarization for Low-Power Wearables",
            "abstract": "A lightweight quantized model for real-time diarization.",
            "year": 2024,
            "url": "https://www.semanticscholar.org/paper/abc123456",
            "citationCount": 42,
            "venue": "ICASSP",
            "authors": [{"name": "Charlie Brown"}, {"name": "Dana White"}],
        }
    ]
}


def test_arxiv_atom_parsing():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bus = MessageBus()
    agent = PaperReaderAgent(blackboard=bb, bus=bus)

    notes = agent.parse_arxiv_atom(SAMPLE_ARXIV_XML)
    assert len(notes) == 1
    note = notes[0]
    assert note.title == "Neural Speech Diarization with Transformers"
    assert note.year == 2023
    assert note.authors == ["Alice Smith", "Bob Jones"]
    assert "5% DER" in note.abstract
    assert note.source_api == "arxiv"
    assert note.url == "http://arxiv.org/abs/2305.12345v1"


def test_semantic_scholar_json_parsing():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bus = MessageBus()
    agent = PaperReaderAgent(blackboard=bb, bus=bus)

    notes = agent.parse_semantic_scholar_json(SAMPLE_S2_JSON)
    assert len(notes) == 1
    note = notes[0]
    assert note.title == "On-Device Diarization for Low-Power Wearables"
    assert note.year == 2024
    assert note.citations_count == 42
    assert note.venue == "ICASSP"
    assert note.authors == ["Charlie Brown", "Dana White"]
    assert note.source_api == "semantic_scholar"


def test_paper_reader_blackboard_integration():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bus = MessageBus()
    agent = PaperReaderAgent(blackboard=bb, bus=bus)

    # Inject mock fetch methods
    async def mock_fetch_all(query, max_papers=5):
        return agent.parse_arxiv_atom(SAMPLE_ARXIV_XML), agent.parse_semantic_scholar_json(SAMPLE_S2_JSON)

    agent._fetch_all = mock_fetch_all

    results = asyncio.run(agent.run_phase(max_papers=2))
    assert len(results) == 2
    assert len(bb.paper_notes) == 2
    assert bb.paper_notes[0].title == "Neural Speech Diarization with Transformers"
    assert bb.paper_notes[1].title == "On-Device Diarization for Low-Power Wearables"
