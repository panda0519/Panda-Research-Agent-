"""Wolfram Alpha API client for authoritative mathematical and scientific claim evaluation."""
from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, execute_resilient_sync, get_circuit_breaker

logger = logging.getLogger(__name__)

WOLFRAM_SHORT_ANSWER_API = "https://api.wolframalpha.com/v1/result"
DEFAULT_HARD_CAP_PER_RUN = 5


@dataclass
class WolframResult:
    query: str
    result: str = ""
    is_success: bool = False
    call_count_in_run: int = 0
    error_message: Optional[str] = None


class WolframAlphaClient:
    app_id: Optional[str] = None
    max_calls_per_run: int = DEFAULT_HARD_CAP_PER_RUN
    timeout: float = 10.0
    call_count: int = 0

    def __init__(
        self,
        app_id: Optional[str] = None,
        max_calls_per_run: int = DEFAULT_HARD_CAP_PER_RUN,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.app_id = app_id if app_id is not None else os.environ.get("WOLFRAM_APP_ID", "")
        self.max_calls_per_run = max_calls_per_run
        self.timeout = timeout
        self.call_count: int = 0
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("wolfram")

    def reset_counter(self) -> None:
        """Resets the per-run hard cap call counter."""
        self.call_count = 0

    async def query(self, query: str) -> Optional[WolframResult]:
        """Queries Wolfram Alpha Short Answer API with hard-cap enforcement."""
        if not self.app_id or not self.app_id.strip():
            logger.debug("WolframAlphaClient skipped: WOLFRAM_APP_ID is not set.")
            return None

        if not query or not query.strip():
            return None

        if self.call_count >= self.max_calls_per_run:
            logger.warning(
                "Wolfram Alpha hard cap reached (%d/%d calls). Skipping query to conserve quota.",
                self.call_count,
                self.max_calls_per_run,
            )
            return None

        self.call_count += 1
        current_count = self.call_count

        encoded_q = urllib.parse.quote(query.strip())
        url = f"{WOLFRAM_SHORT_ANSWER_API}?appid={self.app_id.strip()}&i={encoded_q}"

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.get(url)

        resp = await execute_resilient_async("wolfram", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            text_result = resp.text.strip()
            return WolframResult(
                query=query,
                result=text_result,
                is_success=True,
                call_count_in_run=current_count,
            )
        elif resp and getattr(resp, "status_code", 0) in (401, 403):
            logger.warning("Wolfram Alpha authentication failed (status %d)", resp.status_code)
            return WolframResult(
                query=query,
                is_success=False,
                call_count_in_run=current_count,
                error_message="Authentication failed",
            )
        elif resp and getattr(resp, "status_code", 0) == 501:
            logger.debug("Wolfram Alpha could not interpret query: %s", query)
            return WolframResult(
                query=query,
                is_success=False,
                call_count_in_run=current_count,
                error_message="No answer found (HTTP 501)",
            )
        return None

    def query_sync(self, query: str) -> Optional[WolframResult]:
        """Synchronous query with hard-cap enforcement."""
        if not self.app_id or not self.app_id.strip():
            logger.debug("WolframAlphaClient skipped: WOLFRAM_APP_ID is not set.")
            return None

        if not query or not query.strip():
            return None

        if self.call_count >= self.max_calls_per_run:
            logger.warning(
                "Wolfram Alpha hard cap reached (%d/%d calls). Skipping query.",
                self.call_count,
                self.max_calls_per_run,
            )
            return None

        self.call_count += 1
        current_count = self.call_count

        encoded_q = urllib.parse.quote(query.strip())
        url = f"{WOLFRAM_SHORT_ANSWER_API}?appid={self.app_id.strip()}&i={encoded_q}"

        def _call_sync():
            with httpx.Client(timeout=self.timeout) as client:
                return client.get(url)

        resp = execute_resilient_sync("wolfram", _call_sync, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            return WolframResult(
                query=query,
                result=resp.text.strip(),
                is_success=True,
                call_count_in_run=current_count,
            )
        return None


async def query_wolfram(query: str, app_id: Optional[str] = None) -> Optional[WolframResult]:
    """Helper function to execute a Wolfram Alpha query."""
    client = WolframAlphaClient(app_id=app_id)
    return await client.query(query)
