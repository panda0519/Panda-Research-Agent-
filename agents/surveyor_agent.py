"""SurveyorAgent: analyzes landscape and identifies existing commercial/open-source solutions with broader academic search."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from agents.base import BaseAgent
from blackboard import Blackboard, Solution
from message import MessageBus, MessageType
from sources.crossref_client import CrossrefClient, CrossrefWork
from sources.jev_client import JevClient, get_jev_client
from sources.openalex_client import OpenAlexClient, OpenAlexWork
from sources.unpaywall_client import UnpaywallClient

logger = logging.getLogger(__name__)

OPENALEX_API_BASE = "https://api.openalex.org"
CROSSREF_API_BASE = "https://api.crossref.org"


class SurveyorAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 2,
        llm_client: Optional[Any] = None,
        openalex_client: Optional[OpenAlexClient] = None,
        crossref_client: Optional[CrossrefClient] = None,
        unpaywall_client: Optional[UnpaywallClient] = None,
        jev_client: Optional[JevClient] = None,
        mailto: Optional[str] = None,
    ) -> None:
        super().__init__(
            name="SurveyorAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.openalex = openalex_client or OpenAlexClient()
        self.crossref = crossref_client or CrossrefClient()
        self.unpaywall = unpaywall_client or UnpaywallClient()
        self.jev = jev_client or get_jev_client()
        self.mailto = mailto or os.environ.get("CROSSREF_MAILTO") or os.environ.get("UNPAYWALL_EMAIL", "research@panda.internal")

    async def fetch_openalex(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Queries OpenAlex API for relational graphs with exponential backoff for HTTP 429."""
        url = f"{OPENALEX_API_BASE}/works"
        params: Dict[str, Any] = {
            "search": query.strip(),
            "per_page": min(limit, 10),
            "sort": "relevance_score:desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto.strip()

        backoff = [1, 2, 4]
        for attempt in range(len(backoff) + 1):
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429:
                        if attempt < len(backoff):
                            delay = backoff[attempt]
                            logger.warning("OpenAlex 429 rate limit hit. Backing off %ds...", delay)
                            await asyncio.sleep(delay)
                            continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("results", [])
            except Exception as exc:
                if attempt == len(backoff):
                    logger.debug("OpenAlex fetch failed after retries: %s", exc)
                    return []
                await asyncio.sleep(backoff[attempt])
        return []

    async def fetch_crossref(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Queries Crossref REST API for works with mailto Polite Pool parameter and exponential backoff."""
        url = f"{CROSSREF_API_BASE}/works"
        params: Dict[str, Any] = {
            "query": query.strip(),
            "rows": min(limit, 10),
            "sort": "relevance",
        }
        if self.mailto:
            params["mailto"] = self.mailto.strip()

        backoff = [1, 2, 4]
        for attempt in range(len(backoff) + 1):
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429:
                        if attempt < len(backoff):
                            delay = backoff[attempt]
                            logger.warning("Crossref 429 rate limit hit. Backing off %ds...", delay)
                            await asyncio.sleep(delay)
                            continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("message", {}).get("items", [])
            except Exception as exc:
                if attempt == len(backoff):
                    logger.debug("Crossref fetch failed after retries: %s", exc)
                    return []
                await asyncio.sleep(backoff[attempt])
        return []

    async def route_dois_through_unpaywall(self, dois: List[str]) -> List[Dict[str, Any]]:
        """Routes discovered DOIs through Unpaywall middleware to find open access full text."""
        resolved: List[Dict[str, Any]] = []
        for doi in dois:
            if not doi:
                continue
            try:
                oa_paper = await self.unpaywall.get_paper_by_doi(doi)
                if oa_paper and oa_paper.is_oa:
                    resolved.append({
                        "doi": doi,
                        "is_oa": True,
                        "pdf_url": oa_paper.pdf_url,
                        "oa_url": oa_paper.oa_url,
                        "title": oa_paper.title,
                    })
            except Exception as exc:
                logger.debug("Unpaywall routing skipped for %s: %s", doi, exc)
        return resolved

    async def _run(self) -> List[Solution]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        sources_summary = "\n".join([f"- {s.title} ({s.url}): {s.snippet[:200]}" for s in self.blackboard.sources[:10]])
        papers_summary = "\n".join([f"- {p.title} ({p.url}): {p.abstract[:200]}" for p in self.blackboard.paper_notes[:5]])

        # Broader Academic Discovery Ladder: OpenAlex -> Crossref -> Baseline
        academic_discovery_lines: List[str] = []
        try:
            # 1. Primary: OpenAlex
            oa_works = await self.openalex.search_works(f"{topic} systems frameworks architecture", limit=3)
            if oa_works:
                self.blackboard.metadata["surveyor_academic_search"] = "openalex"
                for w in oa_works:
                    year_str = f" ({w.publication_year})" if w.publication_year else ""
                    cites_str = f" [{w.cited_by_count} citations]" if w.cited_by_count else ""
                    concepts_str = f" (Concepts: {', '.join(w.concepts[:3])})" if w.concepts else ""
                    academic_discovery_lines.append(f"- [OpenAlex] {w.title}{year_str}{cites_str}{concepts_str}: {w.primary_location_url or w.doi or ''}")
            else:
                # 2. Backup: Crossref
                cr_works = await self.crossref.search_works(f"{topic} architecture system", limit=3)
                if cr_works:
                    self.blackboard.metadata["surveyor_academic_search"] = "crossref"
                    for w in cr_works:
                        year_str = f" ({w.year})" if w.year else ""
                        cites_str = f" [{w.is_referenced_by_count} citations]" if w.is_referenced_by_count else ""
                        academic_discovery_lines.append(f"- [Crossref] {w.title}{year_str}{cites_str}: {w.url or w.doi or ''}")
                else:
                    self.blackboard.metadata["surveyor_academic_search"] = "baseline"
        except Exception as disc_exc:
            logger.debug("SurveyorAgent academic discovery fallback: %s", disc_exc)
            self.blackboard.metadata["surveyor_academic_search"] = "baseline"

        academic_context = "\n".join(academic_discovery_lines)

        prompt = f"""You are a Principal AI Technical Surveyor and Competitive Landscape Architect.
Analyze the current state of the art, commercial products, open-source libraries, and academic implementations for:
Topic: {topic}
Project Context: {context}

GATHERED SOURCES:
{sources_summary or 'None available'}

ACADEMIC PAPERS:
{papers_summary or 'None available'}

BROADER ACADEMIC DISCOVERY (OpenAlex / Crossref):
{academic_context or 'None available'}

Extract 3 to 6 prominent existing solutions (commercial tools, open source frameworks, or key architectures).
For each solution, specify:
1. name: string
2. category: "commercial", "open_source", or "academic"
3. description: concise overview of how it works and what it does
4. strengths: list of strings (strengths and capabilities)
5. limitations: list of strings (known drawbacks, performance bounds, or pricing/platform restrictions)
6. sources: list of URLs from the gathered sources if applicable

Return ONLY a JSON array of objects matching these keys.
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "claude-sonnet-5"),
                temperature=self.config.get("temperature", 0.3),
            )
            data = self.parse_json_response(raw_text)
            solutions: List[Solution] = []
            for item in data:
                if isinstance(item, dict) and "name" in item:
                    sol = Solution(
                        name=str(item.get("name", "")).strip(),
                        category=str(item.get("category", "open_source")).strip(),
                        description=str(item.get("description", "")).strip(),
                        strengths=item.get("strengths", []),
                        limitations=item.get("limitations", []),
                        sources=item.get("sources", []),
                    )
                    self.blackboard.add_solution(sol)
                    solutions.append(sol)

            self.send_message(
                recipient="*",
                msg_type=MessageType.SOLUTIONS_IDENTIFIED,
                payload={"count": len(solutions), "solutions": [s.name for s in solutions]},
            )
            return solutions
        except Exception as exc:
            logger.error("SurveyorAgent failed: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            return []
