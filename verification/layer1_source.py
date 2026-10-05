"""Layer 1: Deterministic Source Verification.

Performs URL reachability checks, domain reputation scoring, multi-engine agreement
boosting, and drops dead links or spam domains.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import yaml

from blackboard import Source
from search.url_normalizer import extract_domain

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "verification.yaml"


def load_verification_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class Layer1SourceVerifier:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or load_verification_config().get("layer1", {})
        self.timeout = float(cfg.get("timeout_seconds", 4.0))
        self.min_trust = float(cfg.get("min_trust_score", 0.5))
        self.disallowed_domains = set(cfg.get("disallowed_domains", []))
        self.high_trust_domains = set(cfg.get("high_trust_domains", []))

    async def verify_sources(self, sources: List[Source]) -> List[Source]:
        """Filters, reaches, and scores sources deterministically."""
        verified: List[Source] = []
        tasks = [self._check_source(s) for s in sources]
        results = await asyncio.gather(*tasks)

        for source, keep in results:
            if keep:
                verified.append(source)
        return verified

    async def _check_source(self, source: Source) -> Tuple[Source, bool]:
        domain = extract_domain(source.url)
        source.domain = domain

        # Filter out disallowed spam domains
        if domain in self.disallowed_domains or any(d in domain for d in self.disallowed_domains):
            logger.info("Dropping source from disallowed domain: %s", source.url)
            return source, False

        # Filter out empty snippet & empty title
        if not source.snippet.strip() and not source.title.strip():
            return source, False

        # Calculate base domain trust
        base_trust = 1.0
        if domain in self.high_trust_domains or any(d in domain for d in self.high_trust_domains):
            base_trust += 0.5

        # Cross-engine agreement boost
        engine_count = len(source.engines)
        if engine_count >= 2:
            base_trust += 0.3 * (engine_count - 1)
        elif engine_count == 1:
            base_trust -= 0.1  # Slight single-engine caveat

        source.trust_score = round(max(0.1, base_trust), 2)

        # Check reachability (HEAD or fast GET) for non-synthetic tests
        if not source.url.startswith("https://mock") and not source.url.startswith("http://mock"):
            is_alive = await self._is_reachable(source.url)
            source.is_reachable = is_alive
            if not is_alive:
                source.trust_score *= 0.5
                if source.trust_score < self.min_trust:
                    return source, False

        return source, (source.trust_score >= self.min_trust)

    async def _is_reachable(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.head(url)
                if resp.status_code < 400:
                    return True
                # Fallback to GET for servers rejecting HEAD
                resp = await client.get(url)
                return resp.status_code < 400
        except Exception:
            return False
