"""OpenAlex client for broad academic discovery, citation metrics, and topic indexing."""
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

OPENALEX_API_BASE = "https://api.openalex.org"


@dataclass
class OpenAlexWork:
    id: str
    doi: Optional[str] = None
    title: str = ""
    publication_year: Optional[int] = None
    cited_by_count: int = 0
    concepts: List[str] = field(default_factory=list)
    primary_location_url: Optional[str] = None
    pdf_url: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    abstract: Optional[str] = None
    is_oa: bool = False
    type: Optional[str] = None


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Reconstructs linear abstract text from OpenAlex inverted index representation."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return ""
    pos_word: List[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, int):
                    pos_word.append((pos, str(word)))
    if not pos_word:
        return ""
    pos_word.sort(key=lambda x: x[0])
    return " ".join([w for _, w in pos_word])


class OpenAlexClient:
    api_key: Optional[str] = None
    mailto: Optional[str] = None
    timeout: float = 10.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        mailto: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENALEX_API_KEY", "")
        self.mailto = mailto or os.environ.get("CROSSREF_MAILTO", "") or os.environ.get("UNPAYWALL_EMAIL", "")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("openalex")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "PandaResearchAgent/1.0",
        }
        if self.api_key and self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    async def search_works(self, query: str, limit: int = 5) -> List[OpenAlexWork]:
        """Searches OpenAlex works matching a research query."""
        if not query or not query.strip():
            return []

        url = f"{OPENALEX_API_BASE}/works"
        params: Dict[str, Any] = {
            "search": query.strip(),
            "per_page": min(limit, 10),
            "sort": "relevance_score:desc",
        }
        if self.mailto and self.mailto.strip():
            params["mailto"] = self.mailto.strip()
        if self.api_key and self.api_key.strip() and "Authorization" not in self._get_headers():
            params["api_key"] = self.api_key.strip()

        headers = self._get_headers()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=headers)

        resp = await execute_resilient_async("openalex", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            results: List[OpenAlexWork] = []
            items = data.get("results", []) if isinstance(data, dict) else []
            for item in items[:limit]:
                authorships = item.get("authorships", [])
                authors_list = [
                    a.get("author", {}).get("display_name", "")
                    for a in authorships
                    if isinstance(a, dict) and a.get("author", {}).get("display_name")
                ]
                concepts = [
                    c.get("display_name", "")
                    for c in item.get("concepts", [])
                    if isinstance(c, dict) and c.get("display_name")
                ]
                prim_loc = item.get("primary_location") or {}
                pdf_url = prim_loc.get("pdf_url")
                landing_url = prim_loc.get("landing_page_url") or item.get("doi") or item.get("id")
                abstract_text = reconstruct_abstract(item.get("abstract_inverted_index"))

                results.append(
                    OpenAlexWork(
                        id=str(item.get("id", "")),
                        doi=item.get("doi"),
                        title=item.get("title", "").strip() if item.get("title") else "Untitled",
                        publication_year=item.get("publication_year"),
                        cited_by_count=item.get("cited_by_count", 0),
                        concepts=concepts[:5],
                        primary_location_url=landing_url,
                        pdf_url=pdf_url,
                        authors=authors_list,
                        abstract=abstract_text or None,
                        is_oa=item.get("open_access", {}).get("is_oa", False) if isinstance(item.get("open_access"), dict) else False,
                        type=item.get("type"),
                    )
                )
            return results
        return []

    async def get_work_by_doi(self, doi: str) -> Optional[OpenAlexWork]:
        """Fetches a work by DOI from OpenAlex."""
        clean_doi = doi.strip()
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", clean_doi)
        if doi_match:
            clean_doi = doi_match.group(0)

        encoded = urllib.parse.quote(f"https://doi.org/{clean_doi}", safe="")
        url = f"{OPENALEX_API_BASE}/works/{encoded}"
        params: Dict[str, Any] = {}
        if self.mailto:
            params["mailto"] = self.mailto.strip()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=self._get_headers())

        resp = await execute_resilient_async("openalex", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            item = resp.json()
            authorships = item.get("authorships", [])
            authors_list = [
                a.get("author", {}).get("display_name", "")
                for a in authorships
                if isinstance(a, dict) and a.get("author", {}).get("display_name")
            ]
            concepts = [
                c.get("display_name", "")
                for c in item.get("concepts", [])
                if isinstance(c, dict) and c.get("display_name")
            ]
            prim_loc = item.get("primary_location") or {}
            abstract_text = reconstruct_abstract(item.get("abstract_inverted_index"))
            return OpenAlexWork(
                id=str(item.get("id", "")),
                doi=item.get("doi"),
                title=item.get("title", "").strip() if item.get("title") else "Untitled",
                publication_year=item.get("publication_year"),
                cited_by_count=item.get("cited_by_count", 0),
                concepts=concepts[:5],
                primary_location_url=prim_loc.get("landing_page_url") or item.get("doi"),
                pdf_url=prim_loc.get("pdf_url"),
                authors=authors_list,
                abstract=abstract_text or None,
                is_oa=item.get("open_access", {}).get("is_oa", False) if isinstance(item.get("open_access"), dict) else False,
                type=item.get("type"),
            )
        return None


async def search_openalex(query: str, limit: int = 5, api_key: Optional[str] = None) -> List[OpenAlexWork]:
    """Helper function to search OpenAlex."""
    client = OpenAlexClient(api_key=api_key)
    return await client.search_works(query=query, limit=limit)
