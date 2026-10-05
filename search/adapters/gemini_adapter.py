"""Optional Gemini Search Adapter using Google Search grounding."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from llm.client import extract_json
from search.adapters.base import BaseSearchAdapter, SearchResult

logger = logging.getLogger(__name__)


class GeminiSearchAdapter(BaseSearchAdapter):
    name: str = "gemini_google_search"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client: Any = None
        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning("Could not initialize Gemini client: %s", e)
        self._genai = self._client

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self.api_key or not self._client:
            return []

        prompt = f"""Search Google for technical information on the query: '{query}'.
Return ONLY a valid JSON array of objects with keys: "url", "title", "snippet".
Limit to {max_results} top results.
"""
        try:
            model_name = os.getenv("GEMINI_MODEL", "models/gemini-flash-latest")
            response = self._client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return self._parse_results(response.text or "")
        except Exception as exc:
            logger.error("Gemini search adapter failed: %s", exc)
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
        except Exception:
            return []
