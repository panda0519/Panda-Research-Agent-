"""Crossref API client for academic publication metadata, citation counts, and publisher registries."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, get_circuit_breaker

logger = logging.getLogger(__name__)

CROSSREF_API_BASE = "https://api.crossref.org"


@dataclass
class CrossrefWork:
    doi: str
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    container_title: Optional[str] = None
    is_referenced_by_count: int = 0
    url: Optional[str] = None
    type: Optional[str] = None
    abstract: Optional[str] = None


class CrossrefClient:
    mailto: Optional[str] = None
    timeout: float = 10.0

    def __init__(
        self,
        mailto: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.mailto = mailto or os.environ.get("CROSSREF_MAILTO", "")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("crossref")

    def _get_headers(self) -> Dict[str, str]:
        ua = "PandaResearchAgent/1.0"
        if self.mailto and self.mailto.strip():
            ua += f" (mailto:{self.mailto.strip()})"
        return {
            "Accept": "application/json",
            "User-Agent": ua,
        }

    async def search_works(self, query: str, limit: int = 5) -> List[CrossrefWork]:
        """Searches Crossref publications matching query."""
        if not query or not query.strip():
            return []

        url = f"{CROSSREF_API_BASE}/works"
        params: Dict[str, Any] = {
            "query": query.strip(),
            "rows": min(limit, 10),
            "sort": "relevance",
        }
        if self.mailto and self.mailto.strip():
            params["mailto"] = self.mailto.strip()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=self._get_headers())

        resp = await execute_resilient_async("crossref", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            results: List[CrossrefWork] = []
            for item in items[:limit]:
                titles = item.get("title", [])
                title = titles[0].strip() if titles and isinstance(titles, list) else "Untitled"
                authors_list: List[str] = []
                for a in item.get("author", []):
                    given = a.get("given", "")
                    family = a.get("family", "")
                    full = f"{given} {family}".strip()
                    if full:
                        authors_list.append(full)
                    elif a.get("name"):
                        authors_list.append(a.get("name"))

                year = None
                issued = item.get("issued", {}).get("date-parts", [])
                if issued and isinstance(issued[0], list) and issued[0]:
                    try:
                        year = int(issued[0][0])
                    except (ValueError, TypeError):
                        pass

                containers = item.get("container-title", [])
                container = containers[0] if containers and isinstance(containers, list) else None
                raw_abstract = item.get("abstract", "") or ""
                clean_abstract = re.sub(r"<[^>]+>", "", raw_abstract).strip() if raw_abstract else None

                results.append(
                    CrossrefWork(
                        doi=item.get("DOI", ""),
                        title=title,
                        authors=authors_list,
                        year=year,
                        container_title=container,
                        is_referenced_by_count=item.get("is-referenced-by-count", 0),
                        url=item.get("URL") or f"https://doi.org/{item.get('DOI', '')}",
                        type=item.get("type"),
                        abstract=clean_abstract,
                    )
                )
            return results
        return []
    async def get_work_by_doi(self, doi: str) -> Optional[CrossrefWork]:
        """Fetches metadata for a given DOI from Crossref."""
        clean_doi = doi.strip()
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", clean_doi)
        if doi_match:
            clean_doi = doi_match.group(0)

        encoded = urllib.parse.quote(clean_doi, safe="")
        url = f"{CROSSREF_API_BASE}/works/{encoded}"
        params: Dict[str, Any] = {}
        if self.mailto and self.mailto.strip():
            params["mailto"] = self.mailto.strip()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=self._get_headers())

        resp = await execute_resilient_async("crossref", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            item = resp.json().get("message", {})
            titles = item.get("title", [])
            title = titles[0].strip() if titles and isinstance(titles, list) else "Untitled"
            authors_list = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get("author", [])]
            year = None
            issued = item.get("issued", {}).get("date-parts", [])
            if issued and isinstance(issued[0], list) and issued[0]:
                try:
                    year = int(issued[0][0])
                except (ValueError, TypeError):
                    pass
            containers = item.get("container-title", [])
            container = containers[0] if containers and isinstance(containers, list) else None
            raw_abstract = item.get("abstract", "") or ""
            clean_abstract = re.sub(r"<[^>]+>", "", raw_abstract).strip() if raw_abstract else None

            return CrossrefWork(
                doi=item.get("DOI", clean_doi),
                title=title,
                authors=[a for a in authors_list if a],
                year=year,
                container_title=container,
                is_referenced_by_count=item.get("is-referenced-by-count", 0),
                url=item.get("URL") or f"https://doi.org/{clean_doi}",
                type=item.get("type"),
                abstract=clean_abstract,
            )
        return None
async def search_crossref(query: str, limit: int = 5, mailto: Optional[str] = None) -> List[CrossrefWork]:
    """Helper function to search Crossref."""
    client = CrossrefClient(mailto=mailto)
    return await client.search_works(query=query, limit=limit)
