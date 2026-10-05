import asyncio
import tempfile
from blackboard import Blackboard, Gap, Feature
from memory.store import VectorMemoryStore, VoyageEmbeddingClient
from message import MessageBus
from agents.memory_agent import MemoryAgent


def test_vector_memory_store_cosine_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = f"{tmpdir}/test_vectors.json"
        client = VoyageEmbeddingClient(api_key=None)  # Uses deterministic mock embeddings
        store = VectorMemoryStore(store_path=store_path, embedding_client=client)

        store.add_run_digest(
            run_id="run_1",
            topic="on-device speech diarization",
            digest="Explored lightweight PyAnnote and Whisper. Gaps in streaming latency.",
        )
        store.add_run_digest(
            run_id="run_2",
            topic="high throughput database indexing",
            digest="Explored B+ trees vs LSM trees in Rust.",
        )

        # Search for diarization
        results = store.search_similar("speech diarization models", top_k=2)
        assert len(results) >= 1
        top_entry, score = results[0]
        assert top_entry["run_id"] == "run_1"
        assert score > 0.25


def test_memory_agent_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = f"{tmpdir}/memory_agent_test.json"
        store = VectorMemoryStore(store_path=store_path, embedding_client=VoyageEmbeddingClient(api_key=None))

        # First run: add findings and save digest
        bb1 = Blackboard(run_id="run_alpha", topic="speech diarization", project_context="voice app")
        bb1.add_gap(Gap(gap_id="G1", category="technical", title="High Latency", description="Diarization takes >500ms"))
        bb1.add_feature(Feature(feature_id="F1", title="Streaming SincNet", description="Chunked low latency model"))

        bus1 = MessageBus()
        agent1 = MemoryAgent(blackboard=bb1, bus=bus1, store=store)
        asyncio.run(agent1.run_phase(action="save"))

        # Second run: retrieve prior context
        bb2 = Blackboard(run_id="run_beta", topic="speech diarization", project_context="new voice assistant")
        bus2 = MessageBus()
        agent2 = MemoryAgent(blackboard=bb2, bus=bus2, store=store)
        asyncio.run(agent2.run_phase(action="retrieve"))

        assert len(bb2.prior_context_notes) == 1
        assert "run_alpha" in bb2.prior_context_notes[0] or "speech diarization" in bb2.prior_context_notes[0]
        assert "High Latency" in bb2.prior_context_notes[0]
