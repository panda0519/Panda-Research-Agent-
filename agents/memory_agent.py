"""MemoryAgent: manages cross-run memory using local vector storage and Voyage AI embeddings."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard
from memory.store import VectorMemoryStore
from message import MessageBus, MessageType

logger = logging.getLogger(__name__)


class MemoryAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        store: Optional[VectorMemoryStore] = None,
        phase: int = 0,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name="MemoryAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.store = store or VectorMemoryStore()

    async def _run(self, action: str = "retrieve", top_k: int = 3) -> Any:
        if action == "retrieve":
            return await self.retrieve_prior_context(top_k=top_k)
        elif action == "save":
            return await self.save_run_digest()
        else:
            raise ValueError(f"Unknown memory action: {action}")

    async def retrieve_prior_context(self, top_k: int = 3) -> List[Dict[str, Any]]:
        """Queries vector memory for similar previous runs and populates blackboard."""
        query_text = f"Topic: {self.blackboard.topic}\nContext: {self.blackboard.project_context}"
        results = self.store.search_similar(query_text, top_k=top_k)

        matched_notes: List[str] = []
        for entry, score in results:
            note = f"[Prior Run: {entry.get('topic', 'Unknown')}] (Similarity: {score:.2f})\n{entry.get('digest', '')}"
            matched_notes.append(note)

        self.blackboard.prior_context_notes = matched_notes
        self.send_message(
            recipient="*",
            msg_type=MessageType.INFO,
            payload={"action": "prior_memory_retrieved", "matches": len(matched_notes)},
        )
        return [r[0] for r in results]

    async def save_run_digest(self) -> str:
        """Generates a concise digest of the finished run and writes it to vector store."""
        gaps_summary = "; ".join([f"{g.title} ({g.category})" for g in self.blackboard.gaps[:5]])
        features_summary = "; ".join([f"{f.title}" for f in self.blackboard.proposed_features[:5]])
        tech_summary = "; ".join([f"{ts.layer}: {ts.selected_tech}" for ts in self.blackboard.tech_stack[:5]])

        digest = (
            f"Topic: {self.blackboard.topic}\n"
            f"Context: {self.blackboard.project_context}\n"
            f"Key Gaps: {gaps_summary or 'None'}\n"
            f"Proposed Features: {features_summary or 'None'}\n"
            f"Tech Stack: {tech_summary or 'None'}"
        )

        self.store.add_run_digest(
            run_id=self.blackboard.run_id,
            topic=self.blackboard.topic,
            digest=digest,
            metadata={
                "gaps_count": len(self.blackboard.gaps),
                "features_count": len(self.blackboard.proposed_features),
            },
        )
        return digest
