"""CORE API client for searching open access research outputs and full text downloads."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, get_circuit_breaker

logger = logging.getLogger(__name__)

CORE_API_BASE = "https://api.core.ac.uk/v3"


@dataclass
class CorePaper:
    core_id: str
    doi: Optional[str] = None
    title: str = ""
    abstract: Optional[str] = None
    download_url: Optional[str] = None
    full_text_url: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    publisher: Optional[str] = None
    document_type: Optional[str] = None


class CoreClient:
    api_key: Optional[str] = None
    timeout: float = 10.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("CORE_API_KEY", "")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("core")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "PandaResearchAgent/1.0",
        }
        if self.api_key and self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    async def search_works(self, query: str, limit: int = 5) -> List[CorePaper]:
        """Searches CORE API for research papers matching a query."""
        if not self.api_key or not self.api_key.strip():
            logger.debug("CoreClient skipped: CORE_API_KEY is not set.")
            return []

        if not query or not query.strip():
            return []

        url = f"{CORE_API_BASE}/search/works"
        params = {"q": query.strip(), "limit": min(limit, 10)}
        headers = self._get_headers()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=headers)

        resp = await execute_resilient_async("core", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            results: List[CorePaper] = []
            items = data.get("results", []) if isinstance(data, dict) else []
            for item in items[:limit]:
                authors_list: List[str] = []
                for a in item.get("authors", []):
                    if isinstance(a, dict) and a.get("name"):
                        authors_list.append(a["name"])
                    elif isinstance(a, str):
                        authors_list.append(a)

                results.append(
                    CorePaper(
                        core_id=str(item.get("id", "")),
                        doi=item.get("doi"),
                        title=item.get("title", "").strip(),
                        abstract=item.get("abstract"),
                        download_url=item.get("downloadUrl"),
                        full_text_url=item.get("sourceFulltextUrls", [None])[0] if item.get("sourceFulltextUrls") else None,
                        authors=authors_list,
                        year=item.get("yearPublished"),
                        publisher=item.get("publisher"),
                        document_type=item.get("documentType"),
                    )
                )
            return results
        return []

    async def get_work_by_doi(self, doi: str) -> Optional[CorePaper]:
        """Fetches a specific paper by DOI from CORE."""
        if not self.api_key or not self.api_key.strip():
            logger.debug("CoreClient skipped: CORE_API_KEY is not set.")
            return None

        clean_doi = doi.strip()
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", clean_doi)
        if doi_match:
            clean_doi = doi_match.group(0)

        results = await self.search_works(f'doi:"{clean_doi}"', limit=1)
        return results[0] if results else None


async def search_core(query: str, limit: int = 5, api_key: Optional[str] = None) -> List[CorePaper]:
    """Helper function to search CORE."""
    client = CoreClient(api_key=api_key)
    return await client.search_works(query=query, limit=limit)
