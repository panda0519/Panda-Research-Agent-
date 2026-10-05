"""Tavily REST API Search Adapter."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from search.adapters.base import BaseSearchAdapter, SearchResult

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


class TavilySearchAdapter(BaseSearchAdapter):
    name: str = "tavily"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key

    @property
    def api_key(self) -> str:
        return self._api_key or os.environ.get("TAVILY_API_KEY", "")


    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self.api_key:
            logger.warning("TAVILY_API_KEY not set; skipping Tavily search adapter.")
            return []

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_raw_content": False,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(TAVILY_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

            results: List[SearchResult] = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        snippet=item.get("content", ""),
                        engine=self.name,
                        score=float(item.get("score", 1.0)),
                        raw_metadata=item,
                    )
                )
            return results
        except Exception as exc:
            logger.error("Tavily search failed: %s", exc)
            return []
