"""Unpaywall client for Open Access academic full text and PDF resolution."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, get_circuit_breaker

logger = logging.getLogger(__name__)

UNPAYWALL_API_BASE = "https://api.unpaywall.org/v2"


@dataclass
class UnpaywallPaper:
    doi: str
    is_oa: bool = False
    title: Optional[str] = None
    oa_url: Optional[str] = None
    pdf_url: Optional[str] = None
    landing_page_url: Optional[str] = None
    host_type: Optional[str] = None
    version: Optional[str] = None
    license: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None
    journal_name: Optional[str] = None


class UnpaywallClient:
    email: Optional[str] = None
    timeout: float = 10.0

    def __init__(
        self,
        email: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.email = email if email is not None else os.environ.get("UNPAYWALL_EMAIL", "")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("unpaywall")

    @staticmethod
    def clean_doi(doi_or_url: str) -> Optional[str]:
        """Extracts and normalizes a DOI from a DOI string or URL."""
        clean = doi_or_url.strip()
        # Remove common URL prefixes
        match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", clean)
        if match:
            return match.group(0).rstrip(".,;")
        return None

    async def get_paper_by_doi(self, doi_or_url: str) -> Optional[UnpaywallPaper]:
        """Fetches Open Access metadata and PDF download links from Unpaywall."""
        if not self.email or not self.email.strip():
            logger.debug("UnpaywallClient skipped: UNPAYWALL_EMAIL is not set.")
            return None

        doi = self.clean_doi(doi_or_url)
        if not doi:
            logger.debug("Invalid DOI format: %s", doi_or_url)
            return None

        encoded_doi = urllib.parse.quote(doi, safe="")
        url = f"{UNPAYWALL_API_BASE}/{encoded_doi}"
        params = {"email": self.email.strip()}

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params)

        resp = await execute_resilient_async("unpaywall", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            best_oa = data.get("best_oa_location") or {}
            return UnpaywallPaper(
                doi=data.get("doi", doi),
                is_oa=data.get("is_oa", False),
                title=data.get("title"),
                oa_url=best_oa.get("url"),
                pdf_url=best_oa.get("url_for_pdf"),
                landing_page_url=best_oa.get("url_for_landing_page"),
                host_type=best_oa.get("host_type"),
                version=best_oa.get("version"),
                license=best_oa.get("license"),
                genre=data.get("genre"),
                year=data.get("year"),
                journal_name=data.get("journal_name"),
            )
        elif resp and getattr(resp, "status_code", 0) == 404:
            logger.debug("DOI not found in Unpaywall: %s", doi)
            return None
        return None


async def fetch_unpaywall_pdf(doi: str, email: Optional[str] = None) -> Optional[UnpaywallPaper]:
    """Helper function to fetch paper OA metadata via Unpaywall."""
    client = UnpaywallClient(email=email)
    return await client.get_paper_by_doi(doi)
