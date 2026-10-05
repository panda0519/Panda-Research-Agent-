"""Asynchronous Web Scraper and Content Extractor for Deep Research."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# Common headers to mimic standard browser navigation
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_html(html_text: str, max_chars: int = 4000) -> str:
    """Strips tags, scripts, styles, and extracts readable text."""
    if not html_text:
        return ""

    # 1. Strip scripts, styles, svgs, noscripts, iframes
    cleaned = re.sub(r"<(script|style|svg|noscript|iframe|nav|footer|header)\b[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Convert common block tags to newlines
    cleaned = re.sub(r"<(p|br|div|h[1-6]|li|tr|section|article)\b[^>]*>", "\n", cleaned, flags=re.IGNORECASE)

    # 3. Strip all remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    # 4. Replace HTML entities
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')

    # 5. Normalize whitespace while preserving line structure
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    text = "\n".join([line for line in lines if line])

    if len(text) > max_chars:
        return text[:max_chars] + "... [truncated]"
    return text


class WebScraper:
    """Resilient async web scraper with concurrency limits and timeouts."""

    def __init__(self, concurrency: int = 5, timeout_s: float = 12.0) -> None:
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = timeout_s

    async def scrape_url(self, url: str, client: Optional[httpx.AsyncClient] = None) -> str:
        """Fetch and extract clean text from a single URL."""
        if not url or not url.startswith("http"):
            return ""

        async with self.semaphore:
            try:
                if client is not None:
                    resp = await client.get(url, headers=DEFAULT_HEADERS, timeout=self.timeout, follow_redirects=True)
                    if resp.status_code == 200:
                        return clean_html(resp.text)
                else:
                    async with httpx.AsyncClient(verify=False) as async_client:
                        resp = await async_client.get(url, headers=DEFAULT_HEADERS, timeout=self.timeout, follow_redirects=True)
                        if resp.status_code == 200:
                            return clean_html(resp.text)
            except Exception as exc:
                logger.debug("Failed to scrape URL %s: %s", url, exc)
            return ""

    async def scrape_urls_batch(self, urls: List[str]) -> Dict[str, str]:
        """Scrapes multiple URLs concurrently."""
        valid_urls = [u for u in urls if u and u.startswith("http")]
        if not valid_urls:
            return {}

        results: Dict[str, str] = {}
        async with httpx.AsyncClient(verify=False, timeout=self.timeout) as client:
            tasks = [self.scrape_url(u, client=client) for u in valid_urls]
            extracted_texts = await asyncio.gather(*tasks, return_exceptions=True)

            for u, text in zip(valid_urls, extracted_texts):
                if isinstance(text, str) and text.strip():
                    results[u] = text.strip()

        return results
