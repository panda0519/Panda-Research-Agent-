"""ResearcherAgent: performs multi-query, multi-engine web research and deep scraping."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

from agents.base import BaseAgent
from blackboard import Blackboard, Source
from message import MessageBus, MessageType
from search.orchestrator import SearchOrchestrator
from search.url_normalizer import normalize_url
from sources.web_scraper import WebScraper
from verification.layer1_source import Layer1SourceVerifier

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        orchestrator: Optional[SearchOrchestrator] = None,
        layer1_verifier: Optional[Layer1SourceVerifier] = None,
        web_scraper: Optional[WebScraper] = None,
        phase: int = 1,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name="ResearcherAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.orchestrator = orchestrator or SearchOrchestrator()
        self.verifier = layer1_verifier or Layer1SourceVerifier()
        self.scraper = web_scraper or WebScraper()

    async def _run(self, max_results_per_engine: int = 5) -> List[Source]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        # 1. Retrieve query plan or build fallback queries
        query_plan = self.blackboard.metadata.get("query_plan", {})
        web_queries: List[str] = query_plan.get("web_queries", [])
        if not web_queries:
            canonical = self.blackboard.metadata.get("canonical_topic", topic[:100])
            web_queries = [
                f"{canonical} architecture benchmark",
                f"{canonical} github open source",
                f"{canonical} state of the art tools",
                f"{canonical} limitations deployment",
            ]

        logger.info("ResearcherAgent launching deep multi-query search across %d queries...", len(web_queries))

        try:
            backends = self.config.get(
                "search_backends",
                ["tavily", "gemini_google_search", "claude_web_search", "duckduckgo"],
            )

            # 2. Run searches across all queries concurrently
            search_tasks = [
                self.orchestrator.search(
                    query=q,
                    max_results_per_engine=max_results_per_engine,
                    enabled_backends=backends,
                )
                for q in web_queries
            ]
            batch_results = await asyncio.gather(*search_tasks, return_exceptions=True)

            # 3. Deduplicate and merge multi-query findings
            merged_by_url: Dict[str, Source] = {}
            for res_list in batch_results:
                if isinstance(res_list, list):
                    for s in res_list:
                        norm = normalize_url(s.url)
                        if norm not in merged_by_url:
                            merged_by_url[norm] = s
                        else:
                            existing = merged_by_url[norm]
                            existing.engines = sorted(list(set(existing.engines + s.engines)))
                            existing.trust_score = max(existing.trust_score, s.trust_score) + 0.1
                            if len(s.snippet) > len(existing.snippet):
                                existing.snippet = s.snippet

            raw_sources = list(merged_by_url.values())

            # 4. Deep scrape top high-priority URLs to enrich snippets with full text
            scrape_targets = [s.url for s in raw_sources[:20] if s.url.startswith("http")]
            if scrape_targets:
                logger.info("ResearcherAgent deep-scraping %d high-priority web pages...", len(scrape_targets))
                scraped_data = await self.scraper.scrape_urls_batch(scrape_targets)
                for s in raw_sources:
                    if s.url in scraped_data and scraped_data[s.url]:
                        full_content = scraped_data[s.url]
                        # Append scraped rich context to snippet
                        s.snippet = f"{s.snippet}\n\n[Full Content Excerpt]: {full_content[:1500]}".strip()

            # 5. Layer 1 deterministic verification
            verified_sources = await self.verifier.verify_sources(raw_sources)

            self.blackboard.add_sources(verified_sources)
            self.send_message(
                recipient="*",
                msg_type=MessageType.SEARCH_RESULT,
                payload={
                    "count": len(verified_sources),
                    "urls": [s.url for s in verified_sources],
                },
            )
            return verified_sources
        except Exception as exc:
            logger.error("ResearcherAgent failed: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            return []

