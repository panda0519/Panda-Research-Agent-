"""DuckDuckGo Search Adapter: zero-key free web search engine."""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import List, Optional

import httpx

from search.adapters.base import BaseSearchAdapter, SearchResult

logger = logging.getLogger(__name__)


class DuckDuckGoSearchAdapter(BaseSearchAdapter):
    name: str = "duckduckgo"

    def __init__(self, timeout_s: float = 12.0) -> None:
        self.timeout = timeout_s

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        encoded = urllib.parse.quote_plus(clean_query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                return self._parse_html(resp.text, max_results=max_results)
        except Exception as exc:
            logger.debug("DuckDuckGo search failed: %s", exc)
            return []

    def _parse_html(self, html: str, max_results: int = 5) -> List[SearchResult]:
        results: List[SearchResult] = []
        if not html:
            return results

        # Match result blocks in DuckDuckGo HTML
        # Result links typically have class="result__url" or class="result__snippet"
        # Or <a class="result__a" href="//duckduckgo.com/l/?uddg=..." >Title</a>
        link_matches = re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        snippets = re.findall(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        extracted_urls_titles: List[tuple[str, str]] = []
        for match in link_matches:
            raw_url = match.group(1)
            raw_title = match.group(2)

            # DuckDuckGo redirect wrapper: /l/?uddg=https%3A%2F%2F...
            if "uddg=" in raw_url:
                parsed_params = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                real_url = parsed_params.get("uddg", [raw_url])[0]
            else:
                real_url = raw_url

            # Clean title tags
            clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
            if real_url.startswith("http") and clean_title:
                extracted_urls_titles.append((real_url, clean_title))

        for i, (u, t) in enumerate(extracted_urls_titles[:max_results]):
            snippet_text = ""
            if i < len(snippets):
                snippet_text = re.sub(r"<[^>]+>", "", snippets[i]).strip()

            results.append(
                SearchResult(
                    url=u,
                    title=t,
                    snippet=snippet_text or t,
                    engine=self.name,
                    score=1.0,
                )
            )

        return results
