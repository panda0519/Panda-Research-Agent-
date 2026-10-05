"""Three-Layer Verification Pipeline coordinator."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from blackboard import Blackboard, ClaimVerification, Source
from llm.client import LLMClient
from verification.layer1_source import Layer1SourceVerifier, load_verification_config
from verification.layer2_claim import Layer2ClaimVerifier
from verification.layer3_consistency import Layer3ConsistencyVerifier

logger = logging.getLogger(__name__)


class VerificationPipeline:
    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.config = load_verification_config()
        self.layer1 = Layer1SourceVerifier(self.config.get("layer1"))
        l2_cfg = self.config.get("layer2", {})
        self.layer2 = Layer2ClaimVerifier(
            llm_client=llm_client,
            model=l2_cfg.get("model", "claude-3-5-haiku-20241022"),
        )
        l3_cfg = self.config.get("layer3", {})
        self.layer3 = Layer3ConsistencyVerifier(
            llm_client=llm_client,
            model=l3_cfg.get("model", "claude-sonnet-5"),
        )

    async def verify_layer1_sources(self, sources: List[Source]) -> List[Source]:
        """Runs Layer 1 deterministic source validation."""
        return await self.layer1.verify_sources(sources)

    async def verify_layer2_claims(
        self,
        agent_name: str,
        text_content: str,
        blackboard: Blackboard,
    ) -> List[ClaimVerification]:
        """Runs Layer 2 LLM claim checking and updates Blackboard."""
        verifications = await self.layer2.verify_claims(
            agent_name=agent_name,
            text_content=text_content,
            available_sources=blackboard.sources,
            available_papers=blackboard.paper_notes,
        )
        for v in verifications:
            blackboard.add_claim_verification(v)
        return verifications

    async def verify_layer3_consistency(self, blackboard: Blackboard) -> List[str]:
        """Runs Layer 3 cross-claim consistency audit."""
        return await self.layer3.verify_consistency(blackboard)

    @staticmethod
    def format_badge(status: str, single_engine: bool = False) -> str:
        """Returns visual markdown badge for report rendering."""
        status_upper = status.upper()
        if status_upper == "CONFIRMED":
            if single_engine:
                return "`✓ confirmed (⚠ single-source)`"
            return "`✓ confirmed`"
        elif status_upper == "CONTRADICTED":
            return "`✗ contradicted`"
        elif status_upper == "UNSUPPORTED":
            return "`⚠ unsupported`"
        else:
            return "`? unverified`"
