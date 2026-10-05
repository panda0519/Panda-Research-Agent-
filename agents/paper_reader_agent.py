"""PaperReaderAgent: searches and extracts academic literature from arXiv, Semantic Scholar, and CORE with Unpaywall and CORE Open Access resolution."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import httpx

from agents.base import BaseAgent
from blackboard import Blackboard, PaperNote
from message import MessageBus, MessageType
from sources.core_client import CoreClient, CorePaper
from sources.jev_client import JevClient, get_jev_client
from sources.unpaywall_client import UnpaywallClient

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"


class PaperReaderAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 1,
        llm_client: Optional[Any] = None,
        unpaywall_client: Optional[UnpaywallClient] = None,
        core_client: Optional[CoreClient] = None,
        jev_client: Optional[JevClient] = None,
    ) -> None:
        super().__init__(
            name="PaperReaderAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.unpaywall = unpaywall_client or UnpaywallClient()
        self.core = core_client or CoreClient()
        self.jev = jev_client or get_jev_client()

    async def discover_papers(self, queries: List[str], limit_per_query: int = 5) -> List[PaperNote]:
        """Phase B1: Concurrently queries arXiv, Semantic Scholar, and CORE for candidate academic papers."""
        all_candidate_notes: List[PaperNote] = []

        async def _fetch_for_query(q: str) -> List[PaperNote]:
            arxiv_task = self.fetch_arxiv(q, limit=limit_per_query)
            s2_task = self.fetch_semantic_scholar(q, limit=limit_per_query)
            core_task = self.fetch_core(q, limit=limit_per_query)
            results = await asyncio.gather(arxiv_task, s2_task, core_task, return_exceptions=True)
            
            q_notes: List[PaperNote] = []
            for res in results:
                if isinstance(res, list):
                    q_notes.extend(res)
            return q_notes

        tasks = [_fetch_for_query(q.strip()) for q in queries if q.strip()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_candidate_notes.extend(res)

        # Deduplicate candidates across queries and sources
        seen_titles = set()
        deduped: List[PaperNote] = []
        for p in all_candidate_notes:
            norm_title = p.title.strip().lower()
            if norm_title and norm_title not in seen_titles and len(norm_title) > 3:
                seen_titles.add(norm_title)
                deduped.append(p)

        return deduped

    async def triage_relevance(self, papers: List[PaperNote], topic: str) -> List[PaperNote]:
        """Phase B1.5: Relevance triage via TypeSafe Jev noul decisions.
        
        Evaluates one noul question per candidate paper concurrently.
        Fails open below JEV_RELEVANCE_MIN_CONFIDENCE (items are kept, nothing is deleted).
        """
        min_conf = float(os.environ.get("JEV_RELEVANCE_MIN_CONFIDENCE", "0.75"))

        async def _triage_one(p: PaperNote) -> PaperNote:
            context = f"Paper Title: {p.title}\nAbstract: {p.abstract[:500]}\nResearch Topic: {topic}"
            try:
                decision = await self.jev.noul(
                    context=context,
                    options=["RELEVANT", "IRRELEVANT"],
                    confidence_threshold=min_conf,
                    prompt=f"Determine if this academic paper is relevant to the research topic: {topic}",
                )
                if not decision.is_confident:
                    logger.debug("Jev noul below confidence threshold (%.2f < %.2f) for '%s' -> fail-open (kept)", decision.confidence, min_conf, p.title)
            except Exception as exc:
                logger.debug("Jev relevance triage exception for '%s': %s -> fail-open (kept)", p.title, exc)
            return p

        tasks = [_triage_one(p) for p in papers]
        triaged = await asyncio.gather(*tasks, return_exceptions=True)
        return [p for p in triaged if isinstance(p, PaperNote)]

    async def fetch_core(self, query: str, limit: int = 5) -> List[PaperNote]:
        """Fetches papers from CORE API search endpoint."""
        try:
            core_papers = await self.core.search_works(query, limit=limit)
            notes: List[PaperNote] = []
            for cp in core_papers:
                notes.append(
                    PaperNote(
                        title=cp.title,
                        authors=cp.authors,
                        year=cp.year,
                        url=cp.download_url or (f"https://core.ac.uk/works/{cp.core_id}" if cp.core_id else ""),
                        source_api="core",
                        abstract=cp.abstract or "",
                        venue=cp.publisher or "CORE",
                        doi=cp.doi,
                        full_text_url=cp.download_url or cp.full_text_url,
                        is_open_access=bool(cp.download_url or cp.full_text_url),
                        oa_source="core" if (cp.download_url or cp.full_text_url) else None,
                    )
                )
            return notes
        except Exception as exc:
            logger.debug("CORE fetch failed for query '%s': %s", query, exc)
            return []

    async def _run(self, max_papers: int = 15) -> List[PaperNote]:
        topic = self.blackboard.topic
        query_plan = self.blackboard.metadata.get("query_plan", {})
        academic_queries: List[str] = query_plan.get("academic_queries", [])

        if not academic_queries:
            canonical = self.blackboard.metadata.get("canonical_topic", topic[:80])
            clean_q = re.sub(r"[^\w\s-]", " ", canonical)
            words = [w for w in clean_q.split() if len(w) > 2 and w.lower() not in {"the", "and", "for", "with", "this", "that"}]
            academic_queries = [" ".join(words[:4]), f"{' '.join(words[:3])} architecture", f"{' '.join(words[:3])} benchmark"]

        logger.info("PaperReaderAgent starting unified academic pipeline for %d queries...", len(academic_queries))

        # Phase B1: Discovery across arXiv, Semantic Scholar, and CORE
        discovered_papers = await self.discover_papers(academic_queries, limit_per_query=5)

        # Phase B1.5: Relevance Triage via TypeSafe Jev noul (fail-open, nothing deleted)
        triaged_papers = await self.triage_relevance(discovered_papers, topic)
        target_papers = triaged_papers[:max_papers]

        # Phase B2 & B3: Resolve Open Access and Synthesize Takeaways
        for p in target_papers:
            await self._resolve_open_access(p)
            if not p.takeaways and p.abstract:
                p.takeaways = await self._synthesize_takeaways(p)
            self.blackboard.add_paper_note(p)

        # Record provenance on Blackboard metadata
        if any(p.oa_source == "unpaywall" for p in target_papers):
            self.blackboard.metadata["oa_access_mode"] = "unpaywall"
        elif any(p.oa_source == "core" for p in target_papers):
            self.blackboard.metadata["oa_access_mode"] = "core"
        elif any(p.oa_source == "arxiv" for p in target_papers):
            self.blackboard.metadata["oa_access_mode"] = "arxiv"
        else:
            self.blackboard.metadata["oa_access_mode"] = "baseline"

        self.send_message(
            recipient="*",
            msg_type=MessageType.PAPERS_FOUND,
            payload={"count": len(target_papers), "papers": [p.title for p in target_papers]},
        )
        return target_papers

    async def _resolve_open_access(self, paper: PaperNote) -> None:
        """Resolves Open Access full text via Unpaywall (Primary) -> CORE (Backup) -> arXiv/S2."""
        # 1. Check arXiv native PDF
        if paper.source_api == "arxiv":
            paper.is_open_access = True
            paper.oa_source = "arxiv"
            if not paper.full_text_url and "/abs/" in paper.url:
                paper.full_text_url = paper.url.replace("/abs/", "/pdf/") + (".pdf" if not paper.url.endswith(".pdf") else "")
            return

        # 2. Extract DOI if available
        doi = paper.doi
        if not doi:
            match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", paper.url or "")
            if match:
                doi = match.group(0)

        if doi:
            paper.doi = doi
            # Rung 1: Unpaywall
            try:
                unpaywall_paper = await self.unpaywall.get_paper_by_doi(doi)
                if unpaywall_paper and unpaywall_paper.is_oa and (unpaywall_paper.pdf_url or unpaywall_paper.oa_url):
                    paper.is_open_access = True
                    paper.full_text_url = unpaywall_paper.pdf_url or unpaywall_paper.oa_url
                    paper.oa_source = "unpaywall"
                    return
            except Exception as exc:
                logger.debug("Unpaywall resolution skipped for '%s': %s", doi, exc)

            # Rung 2: CORE
            try:
                core_paper = await self.core.get_work_by_doi(doi)
                if not core_paper and paper.title:
                    core_papers = await self.core.search_works(paper.title, limit=1)
                    if core_papers:
                        core_paper = core_papers[0]
                if core_paper and (core_paper.download_url or core_paper.full_text_url):
                    paper.is_open_access = True
                    paper.full_text_url = core_paper.download_url or core_paper.full_text_url
                    paper.oa_source = "core"
                    return
            except Exception as exc:
                logger.debug("CORE resolution skipped for '%s': %s", doi, exc)

        # Rung 3: Semantic Scholar provided Open Access PDF
        if paper.full_text_url:
            paper.is_open_access = True
            paper.oa_source = "semantic_scholar"

    async def _fetch_all(self, query: str, max_papers: int = 5) -> tuple[List[PaperNote], List[PaperNote]]:
        import asyncio
        arxiv_task = self.fetch_arxiv(query, limit=max_papers)
        s2_task = self.fetch_semantic_scholar(query, limit=max_papers)
        results = await asyncio.gather(arxiv_task, s2_task, return_exceptions=True)

        arxiv_notes = results[0] if isinstance(results[0], list) else []
        s2_notes = results[1] if isinstance(results[1], list) else []
        return arxiv_notes, s2_notes

    async def fetch_arxiv(self, query: str, limit: int = 5) -> List[PaperNote]:
        encoded_q = urllib.parse.quote_plus(query)
        url = f"{ARXIV_API_URL}?search_query=all:{encoded_q}&start=0&max_results={limit}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Encoding": "gzip, deflate",
            "Accept": "*/*",
        }
        try:
            async with httpx.AsyncClient(http1=True, http2=False, headers=headers, timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return self.parse_arxiv_atom(resp.text)
        except Exception as exc:
            logger.warning("arXiv fetch failed: %s", exc)
            return []

    def parse_arxiv_atom(self, xml_text: str) -> List[PaperNote]:
        notes: List[PaperNote] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                summary_elem = entry.find("atom:summary", ns)
                published_elem = entry.find("atom:published", ns)
                id_elem = entry.find("atom:id", ns)
                doi_elem = entry.find("arxiv:doi", ns)

                title = title_elem.text.strip().replace("\n", " ") if title_elem is not None and title_elem.text else "Untitled"
                abstract = summary_elem.text.strip().replace("\n", " ") if summary_elem is not None and summary_elem.text else ""
                paper_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
                doi = doi_elem.text.strip() if doi_elem is not None and doi_elem.text else None

                pdf_url = paper_url.replace("/abs/", "/pdf/") + (".pdf" if not paper_url.endswith(".pdf") else "") if "/abs/" in paper_url else None

                year = None
                if published_elem is not None and published_elem.text:
                    try:
                        year = int(published_elem.text[:4])
                    except ValueError:
                        pass

                authors: List[str] = []
                for author_elem in entry.findall("atom:author", ns):
                    name_elem = author_elem.find("atom:name", ns)
                    if name_elem is not None and name_elem.text:
                        authors.append(name_elem.text.strip())

                notes.append(
                    PaperNote(
                        title=title,
                        authors=authors,
                        year=year,
                        url=paper_url,
                        source_api="arxiv",
                        abstract=abstract,
                        venue="arXiv",
                        doi=doi,
                        full_text_url=pdf_url,
                        is_open_access=True,
                        oa_source="arxiv",
                    )
                )
        except Exception as e:
            logger.warning("Error parsing arXiv XML: %s", e)
        return notes

    async def fetch_semantic_scholar(self, query: str, limit: int = 5) -> List[PaperNote]:
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,url,citationCount,venue,externalIds,openAccessPdf",
        }
        headers = {
            "User-Agent": "ResearchAgent/1.0 (https://github.com/example/research_agent; mailto:researcher@example.com)",
        }
        import asyncio
        backoff_delays = [1, 2]
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(SEMANTIC_SCHOLAR_URL, params=params)
                    if resp.status_code == 429:
                        logger.warning("Semantic Scholar 429 rate-limit, retrying in %ds...", backoff_delays[attempt])
                        await asyncio.sleep(backoff_delays[attempt])
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return self.parse_semantic_scholar_json(data)
            except Exception as exc:
                logger.warning("Semantic Scholar fetch attempt %d failed: %s", attempt + 1, exc)
                if attempt == 1:
                    return []
                await asyncio.sleep(backoff_delays[attempt])
        return []

    def parse_semantic_scholar_json(self, data: Dict[str, Any]) -> List[PaperNote]:
        notes: List[PaperNote] = []
        for item in data.get("data", []):
            title = item.get("title", "").strip()
            if not title:
                continue
            abstract = item.get("abstract", "") or ""
            year = item.get("year")
            url = item.get("url") or f"https://www.semanticscholar.org/paper/{item.get('paperId', '')}"
            venue = item.get("venue", "") or ""
            citations = item.get("citationCount")

            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI")
            oa_pdf = item.get("openAccessPdf") or {}
            full_text_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None

            authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
            notes.append(
                PaperNote(
                    title=title,
                    authors=authors,
                    year=year,
                    url=url,
                    source_api="semantic_scholar",
                    abstract=abstract,
                    citations_count=citations,
                    venue=venue,
                    doi=doi,
                    full_text_url=full_text_url,
                    is_open_access=bool(full_text_url),
                    oa_source="semantic_scholar" if full_text_url else None,
                )
            )
        return notes

    async def _synthesize_takeaways(self, paper: PaperNote) -> str:
        prompt = f"""You are an expert AI literature reviewer. Synthesize the key technical contribution of this academic paper for an engineering team:

Title: {paper.title}
Venue / Year: {paper.venue or 'Preprint'} ({paper.year or 'Recent'})
Abstract: {paper.abstract[:1500]}

Provide a high-density 2-4 sentence summary covering:
1. Core Methodology & Mathematical / Algorithmic Mechanism
2. Quantitative Benchmark Results or Performance Metrics (e.g. accuracy, DER, latency, FLOPS)
3. Key Architectural Innovations & Acknowledged Limitations

Return ONLY the plain-text synthesized takeaway.
"""
        try:
            summary = self.llm.generate(
                prompt=prompt,
                system_prompt="You extract high-density technical and empirical insights from academic papers.",
                temperature=0.2,
                max_tokens=250,
            )
            return summary.strip()
        except Exception:
            return paper.abstract[:250] + "..." if paper.abstract else "Academic paper on relevant topic."

