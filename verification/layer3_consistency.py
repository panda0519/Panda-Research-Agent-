"""Layer 3: Cross-Claim & Holistic Report Consistency.

Checks the full accumulated findings across agents for internal contradictions,
orphan citations, and unverified assertions before report generation.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from blackboard import Blackboard
from llm.client import LLMClient, default_llm_client, extract_json

logger = logging.getLogger(__name__)


class Layer3ConsistencyVerifier:
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        model: str = "claude-sonnet-5",
    ) -> None:
        self.llm = llm_client or default_llm_client
        self.model = model

    async def verify_consistency(self, blackboard: Blackboard) -> List[str]:
        """Performs holistic consistency checks across Blackboard entities."""
        issues: List[str] = []

        # 1. Deterministic orphan citation / unverified claim check
        all_known_urls = {s.url for s in blackboard.sources} | {p.url for p in blackboard.paper_notes}

        for sol in blackboard.existing_solutions:
            for u in sol.sources:
                if u and u not in all_known_urls:
                    issues.append(f"Orphan citation in Solution '{sol.name}': URL {u} not found in verified sources.")

        # 2. LLM cross-agent contradiction check
        gaps_text = "\n".join([f"- Gap [{g.gap_id}]: {g.title} - {g.description}" for g in blackboard.gaps])
        solutions_text = "\n".join([f"- Solution [{s.name}]: {s.description} (strengths: {', '.join(s.strengths)})" for s in blackboard.existing_solutions])
        features_text = "\n".join([f"- Feature [{f.feature_id}]: {f.title} - {f.description} (addresses gaps: {', '.join(f.target_gap_ids)})" for f in blackboard.proposed_features])

        prompt = f"""You are a research consistency auditor. Examine the synthesized findings from different agents for contradictions or discrepancies.

EXISTING SOLUTIONS FOUND BY SURVEYOR:
{solutions_text or "None"}

GAPS IDENTIFIED BY GAP ANALYST:
{gaps_text or "None"}

PROPOSED FEATURES BY IDEATOR:
{features_text or "None"}

CHECK FOR:
1. Does any identified "Gap" claim a capability is missing when an existing Solution already provides it?
2. Does any "Proposed Feature" contradict or duplicate an existing Solution without architectural differentiation?
3. Does any feature target non-existent gap IDs?

Return ONLY a JSON array of strings describing any contradictions found (empty array [] if perfectly consistent).
Example:
["Contradiction: Gap G1 claims offline support is missing, but Solution Whisper.cpp explicitly provides offline support."]
"""
        try:
            raw_response = self.llm.generate(
                prompt=prompt,
                model=self.model,
                temperature=0.1,
            )
            llm_issues = self._parse_json_list(raw_response)
            issues.extend(llm_issues)
        except Exception as exc:
            logger.warning("Layer 3 consistency check failed: %s", exc)

        blackboard.consistency_issues = issues
        return issues

    def _parse_json_list(self, text: str) -> List[str]:
        items = extract_json(text)
        if isinstance(items, list):
            return [str(i) for i in items if isinstance(i, str)]
        return []
