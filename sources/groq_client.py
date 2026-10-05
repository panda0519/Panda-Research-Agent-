"""Groq Cloud API client for fast secondary LLM claim verification and cross-checking."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, execute_resilient_sync, get_circuit_breaker

logger = logging.getLogger(__name__)

GROQ_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


class GroqClient:
    api_key: Optional[str] = None
    default_model: str = DEFAULT_GROQ_MODEL
    timeout: float = 20.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = DEFAULT_GROQ_MODEL,
        timeout: float = 20.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
        self.default_model = default_model
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("groq")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "PandaResearchAgent/1.0",
        }

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> Optional[str]:
        """Asynchronously dispatches a chat completion to Groq."""
        if not self.api_key or not self.api_key.strip():
            logger.debug("GroqClient skipped: GROQ_API_KEY is not set.")
            return None

        if not prompt or not prompt.strip():
            return None

        messages: List[Dict[str, str]] = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt.strip()})

        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{GROQ_API_BASE}/chat/completions"
        headers = self._get_headers()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(url, headers=headers, json=payload)

        resp = await execute_resilient_async("groq", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                return msg.get("content", "").strip()
        return None

    def generate_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> Optional[str]:
        """Synchronous generation using httpx.Client."""
        if not self.api_key or not self.api_key.strip():
            logger.debug("GroqClient skipped: GROQ_API_KEY is not set.")
            return None

        messages: List[Dict[str, str]] = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt.strip()})

        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{GROQ_API_BASE}/chat/completions"
        headers = self._get_headers()

        def _call_sync():
            with httpx.Client(timeout=self.timeout) as client:
                return client.post(url, headers=headers, json=payload)

        resp = execute_resilient_sync("groq", _call_sync, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                return msg.get("content", "").strip()
        return None


async def generate_groq(
    prompt: str,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    """Helper function to call Groq completion."""
    client = GroqClient(api_key=api_key)
    return await client.generate(prompt=prompt, system_prompt=system_prompt, model=model)
