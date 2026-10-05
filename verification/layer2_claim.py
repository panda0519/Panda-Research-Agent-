"""Layer 2: Atomic Claim Verification with Multi-Model & Computational Verification.

Extracts atomic factual claims from agent outputs and verifies them against cited
sources, literature evidence, and deterministic/computational checkers:
1. Second-Model Claim Check: Groq (Llama 3.3 70B) -> Gemini / Primary LLM -> Baseline.
2. Computational Claim Check: Wolfram Alpha (hard cap 5) -> Local Deterministic AST -> Baseline.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from blackboard import Blackboard, ClaimVerification, PaperNote, Source
from llm.client import LLMClient, default_llm_client, extract_json
from sources.groq_client import GroqClient
from sources.jev_client import JevClient, decide_consensus_sync
from sources.local_compute import ComputationResult, verify_computational_claim
from sources.wolfram_client import WolframAlphaClient

logger = logging.getLogger(__name__)


class Layer2ClaimVerifier:
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        model: str = "claude-3-5-haiku-20241022",
        wolfram_client: Optional[WolframAlphaClient] = None,
        groq_client: Optional[GroqClient] = None,
        jev_client: Optional[JevClient] = None,
    ) -> None:
        self.llm = llm_client or default_llm_client
        self.model = model
        # Secondary provider setup
        self.groq = groq_client or GroqClient()
        self.wolfram = wolfram_client or WolframAlphaClient()
        self.jev = jev_client or JevClient()

    async def verify_claims(
        self,
        agent_name: str,
        text_content: str,
        blackboard: Optional[Blackboard] = None,
        available_sources: Optional[List[Source]] = None,
        available_papers: Optional[List[PaperNote]] = None,
    ) -> List[ClaimVerification]:
        """Extracts and verifies claims from text against available sources, utilizing fallback ladders."""
        if not text_content or not text_content.strip():
            return []

        # Resolve sources & paper notes
        sources: List[Source] = []
        if blackboard and blackboard.sources:
            sources = blackboard.sources
        elif available_sources:
            sources = available_sources

        papers: List[PaperNote] = []
        if blackboard and blackboard.paper_notes:
            papers = blackboard.paper_notes
        elif available_papers:
            papers = available_papers

        # Build context pool of sources
        source_texts: List[str] = []
        url_engine_map: Dict[str, List[str]] = {}

        for s in sources:
            source_texts.append(f"Source URL: {s.url}\nTitle: {s.title}\nSnippet: {s.snippet}\nEngines: {', '.join(s.engines)}")
            url_engine_map[s.url] = s.engines

        for p in papers:
            source_texts.append(f"Paper URL: {p.url}\nTitle: {p.title}\nAbstract: {p.abstract}")
            url_engine_map[p.url] = [p.source_api]

        sources_context = "\n---\n".join(source_texts[:15])

        prompt = f"""You are a factual claim verification engine.
Analyze the following text produced by {agent_name} and verify its key factual claims against the provided sources.

EVIDENCE SOURCES:
{sources_context}

TEXT TO VERIFY:
{text_content}

INSTRUCTIONS:
1. Extract up to 5 key atomic factual claims made in the text.
2. For each claim, check if it is supported by the evidence sources.
3. Classify status as EXACTLY one of:
   - "CONFIRMED": Claim is directly supported by evidence snippet.
   - "PARTIALLY_SUPPORTED": Claim is partially supported with caveats or minor gaps.
   - "UNSUPPORTED": Evidence doesn't mention or confirm the claim.
   - "CONTRADICTED": Evidence directly contradicts the claim.
   - "NEEDS_HUMAN": Claim is ambiguous or cannot be verified from available evidence.

Return ONLY a JSON array of objects:
[
  {{
    "claim_text": "...",
    "cited_urls": ["https://..."],
    "status": "CONFIRMED",
    "rationale": "Directly supported by ..."
  }}
]
"""
        # Step 1: Second-Model Claim Check Ladder (Groq -> Primary LLM)
        response_text: Optional[str] = None
        model_used = "Baseline (Primary LLM)"
        try:
            if getattr(self.groq, "api_key", None):
                response_text = await self.groq.generate(prompt=prompt, temperature=0.0)
                if response_text:
                    model_used = "Groq (Llama 3.3 70B)"
        except Exception as groq_exc:
            logger.debug("Groq claim check error: %s", groq_exc)

        # Fallback to internal LLM client if Groq fails or is not configured
        if not response_text:
            logger.debug("Groq verification unavailable/empty, using primary LLM.")
            try:
                response_text = self.llm.generate(
                    prompt=prompt,
                    model=self.model,
                    temperature=0.0,
                )
                if response_text:
                    if os.getenv("GEMINI_API_KEY") and not os.getenv("GROQ_API_KEY"):
                        model_used = "Gemini (gemini-2.5-flash)"
                    else:
                        model_used = "Baseline (Primary LLM)"
            except Exception as llm_exc:
                logger.warning("Primary LLM verification failed: %s", llm_exc)
                response_text = None

        comp_used = "Baseline Textual"
        try:
            parsed = self._parse_json(response_text) if response_text else []
            if not parsed and text_content:
                # Deterministic sentence claim verification fallback ladder using JevClient
                sentences = [s.strip() for s in re.split(r"[.!?]\s+", text_content) if len(s.strip()) > 20][:3]
                for s_text in sentences:
                    jev_res = decide_consensus_sync(
                        context=f"Claim: {s_text}\nAvailable Evidence:\n{sources_context}",
                        client=self.jev,
                    )
                    st = jev_res.value if jev_res.value in {"CONFIRMED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NEEDS_HUMAN"} else "NEEDS_HUMAN"
                    parsed.append({
                        "claim_text": s_text,
                        "cited_urls": list(url_engine_map.keys())[:2],
                        "status": st,
                        "rationale": f"[Jev Deterministic Consensus: {jev_res.value}] {jev_res.reasoning}".strip(),
                    })
                model_used = f"Jev Consensus ({self.jev.api_url})"

            verifications: List[ClaimVerification] = []

            for item in parsed:
                if not isinstance(item, dict) or "claim_text" not in item:
                    continue
                claim_text = str(item["claim_text"]).strip()
                cited = item.get("cited_urls", [])

                is_single = False
                for u in cited:
                    engines = url_engine_map.get(u, [])
                    if len(engines) == 1:
                        is_single = True
                        break

                status = str(item.get("status", "NEEDS_HUMAN")).upper()
                if status not in {"CONFIRMED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NEEDS_HUMAN"}:
                    status = "NEEDS_HUMAN"

                rationale = str(item.get("rationale", "")).strip()

                # Step 2: Tie-breaking or primary consensus verification via JevClient
                if self.jev.api_key:
                    jev_res = decide_consensus_sync(
                        context=f"Claim: {claim_text}\nAvailable Evidence:\n{sources_context}",
                        client=self.jev,
                    )
                    status = jev_res.value if jev_res.value in {"CONFIRMED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NEEDS_HUMAN"} else "NEEDS_HUMAN"
                    rationale = f"[Jev Primary Consensus: {jev_res.value}] {jev_res.reasoning}".strip()
                elif status == "NEEDS_HUMAN":
                    jev_res = decide_consensus_sync(
                        context=f"Claim: {claim_text}\nAvailable Evidence:\n{sources_context}",
                        client=self.jev,
                    )
                    if jev_res.confidence >= 0.7 and jev_res.value in {
                        "CONFIRMED",
                        "PARTIALLY_SUPPORTED",
                        "UNSUPPORTED",
                        "CONTRADICTED",
                    }:
                        status = jev_res.value
                        rationale = f"[Jev Consensus: {jev_res.value} (conf {jev_res.confidence:.2f})] {rationale}".strip()

                # Step 3: Computational Claim Check Ladder (Wolfram Alpha -> Local Compute AST -> Textual)
                comp_res: Optional[ComputationResult] = None
                try:
                    # Deterministic local AST computation / asymptotic / unit conversion check
                    comp_res = verify_computational_claim(claim_text)
                    if comp_res:
                        comp_used = "Deterministic AST (Local)"
                        if comp_res.is_verified:
                            if status in ("UNSUPPORTED", "NEEDS_HUMAN"):
                                status = "CONFIRMED"
                            rationale = f"[Deterministic Compute Verified: {comp_res.claim_type.capitalize()}] {comp_res.expression} -> {comp_res.computed_value}. {rationale}".strip()
                        else:
                            status = "CONTRADICTED"
                            rationale = f"[Deterministic Compute Discrepancy] {comp_res.discrepancy_note}. {rationale}".strip()
                    elif self.wolfram.app_id:
                        # Wolfram Alpha check for numerical query if local compute didn't trigger
                        w_res = await self.wolfram.query(claim_text)
                        if w_res and w_res.is_success:
                            comp_used = "Wolfram Alpha"
                            rationale = f"[Wolfram Alpha Checked: {w_res.result}] {rationale}".strip()
                except Exception as comp_exc:
                    logger.debug("Computational claim check error for '%s': %s", claim_text, comp_exc)

                verifications.append(
                    ClaimVerification(
                        claim_text=claim_text,
                        source_agent=agent_name,
                        cited_urls=cited,
                        status=status,
                        single_engine=is_single,
                        rationale=rationale,
                    )
                )

            if blackboard:
                blackboard.metadata["second_model_used"] = f"TypeSafe Jev Primary ({self.jev.api_url})" if self.jev.api_key else model_used
                blackboard.metadata["computational_checker_used"] = comp_used
                for v in verifications:
                    blackboard.add_claim_verification(v)
            return verifications
        except Exception as exc:
            logger.warning("Layer 2 claim verification failed: %s", exc)
            return []

    def _parse_json(self, text: Optional[str]) -> List[Dict[str, Any]]:
        if not text:
            return []
        try:
            data = extract_json(text)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []
