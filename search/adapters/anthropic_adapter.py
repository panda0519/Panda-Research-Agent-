"""Anthropic Claude Search Adapter using Claude with structured web research."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from llm.client import LLMClient, default_llm_client, extract_json
from search.adapters.base import BaseSearchAdapter, SearchResult

logger = logging.getLogger(__name__)


class AnthropicSearchAdapter(BaseSearchAdapter):
    name: str = "claude_web_search"

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm = llm_client or default_llm_client

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self.llm.api_key:
            logger.warning("ANTHROPIC_API_KEY not set; skipping AnthropicSearchAdapter.")
            return []

        prompt = f"""You are a deep technical search agent. Research the following topic thoroughly and return the top {max_results} most relevant sources and findings.

Query: {query}

CRITICAL: Return ONLY a valid JSON array of objects with the exact keys "url", "title", "snippet".
Do NOT include markdown fences, extra keys, or narrative outside the JSON array.
Example:
[
  {{"url": "https://arxiv.org/abs/2301.12345", "title": "Paper Title", "snippet": "Detailed snippet..."}}
]
"""
        try:
            # We call Claude with web search or synthesis
            raw_text = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an expert technical researcher.",
                temperature=0.2,
            )
            return self._parse_results(raw_text)
        except Exception as exc:
            logger.error("Anthropic search adapter error: %s", exc)
            return []

    def _parse_results(self, text: str) -> List[SearchResult]:
        try:
            items = extract_json(text)
            results = []
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "url" in item:
                        results.append(
                            SearchResult(
                                url=str(item.get("url", "")).strip(),
                                title=str(item.get("title", "")).strip(),
                                snippet=str(item.get("snippet", "")).strip(),
                                engine=self.name,
                            )
                        )
            return results
        except Exception as e:
            logger.warning("Failed to parse JSON results from Anthropic search: %s", e)
            return []
