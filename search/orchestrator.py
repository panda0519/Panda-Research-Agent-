"""Search Orchestrator: runs multiple search adapters concurrently,
deduplicates results by normalized URL, and merges cross-engine provenance.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from blackboard import Source
from search.adapters import (
    AnthropicSearchAdapter,
    BaseSearchAdapter,
    DuckDuckGoSearchAdapter,
    GeminiSearchAdapter,
    SearchResult,
    TavilySearchAdapter,
)
from search.url_normalizer import extract_domain, normalize_url

logger = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(self, adapters: Optional[List[BaseSearchAdapter]] = None) -> None:
        if adapters is not None:
            self.adapters = adapters
        else:
            self.adapters = [
                TavilySearchAdapter(),
                GeminiSearchAdapter(),
                AnthropicSearchAdapter(),
                DuckDuckGoSearchAdapter(),
            ]

    async def search(
        self,
        query: str,
        max_results_per_engine: int = 5,
        enabled_backends: Optional[List[str]] = None,
    ) -> List[Source]:
        """Runs configured search adapters in parallel and merges results."""
        active_adapters = [
            a for a in self.adapters
            if enabled_backends is None or a.name in enabled_backends
        ]

        if not active_adapters:
            logger.warning("No active search adapters enabled.")
            return []

        tasks = [
            self._safe_search(adapter, query, max_results_per_engine)
            for adapter in active_adapters
        ]

        results_by_adapter: List[List[SearchResult]] = await asyncio.gather(*tasks)

        # Merge and deduplicate by normalized URL
        merged: Dict[str, Dict[str, Any]] = {}

        for adapter_results in results_by_adapter:
            for item in adapter_results:
                if not item.url:
                    continue
                norm_url = normalize_url(item.url)
                if not norm_url:
                    continue

                if norm_url not in merged:
                    merged[norm_url] = {
                        "url": item.url,  # preserve original clean url format
                        "title": item.title or norm_url,
                        "snippet": item.snippet or "",
                        "engines": set([item.engine]),
                        "domain": extract_domain(norm_url),
                        "score": item.score,
                    }
                else:
                    entry = merged[norm_url]
                    entry["engines"].add(item.engine)
                    # Use the richer snippet if available
                    if len(item.snippet) > len(entry["snippet"]):
                        entry["snippet"] = item.snippet
                    if len(item.title) > len(entry["title"]):
                        entry["title"] = item.title
                    entry["score"] = max(entry["score"], item.score)

        # Convert to Blackboard Source objects
        sources: List[Source] = []
        for norm_url, data in merged.items():
            engines_list = sorted(list(data["engines"]))
            # Cross-engine agreement bonus
            trust_score = 1.0 + (0.25 * (len(engines_list) - 1))
            sources.append(
                Source(
                    url=data["url"],
                    title=data["title"],
                    snippet=data["snippet"],
                    engines=engines_list,
                    trust_score=trust_score,
                    domain=data["domain"],
                    is_reachable=True,
                )
            )

        # Sort multi-engine backed sources first
        sources.sort(key=lambda s: (len(s.engines), s.trust_score), reverse=True)
        return sources

    async def _safe_search(
        self, adapter: BaseSearchAdapter, query: str, max_results: int
    ) -> List[SearchResult]:
        try:
            return await adapter.search(query, max_results=max_results)
        except Exception as exc:
            logger.error("Search adapter %s failed: %s", adapter.name, exc)
            return []
