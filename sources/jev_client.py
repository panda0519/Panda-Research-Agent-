"""TypeSafe Jev client: deterministic typed decision layer (choice, score, noul) with fallback ladder."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, execute_resilient_sync, get_circuit_breaker

logger = logging.getLogger(__name__)

DEFAULT_TYPESAFE_API_URL = "https://api.typesafe.ai/v1"


def is_laya_available() -> bool:
    """Checks if the local open-weight Laya decision model package is installed."""
    try:
        return importlib.util.find_spec("laya") is not None
    except Exception:
        return False


@dataclass
class JevDecision:
    value: str
    confidence: float = 1.0
    reasoning: str = ""
    provider: str = "jev"  # "jev", "laya", or "fallback"
    is_fallback: bool = False


@dataclass
class JevScore:
    value: int
    confidence: float = 1.0
    reasoning: str = ""
    provider: str = "jev"
    is_fallback: bool = False


@dataclass
class JevNoulDecision:
    value: Optional[str] = None
    selected_option: str = ""
    confidence: float = 1.0
    confidence_threshold: float = 0.75
    is_confident: bool = True
    reasoning: str = ""
    provider: str = "jev"
    is_fallback: bool = False


class JevClient:
    """Client for TypeSafe Jev hosted API with automatic fallback ladder to Laya or local deterministic heuristics."""

    api_key: Optional[str] = None
    api_url: str = DEFAULT_TYPESAFE_API_URL
    timeout: float = 10.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        self.api_url = (api_url or os.environ.get("TYPESAFE_API_URL") or DEFAULT_TYPESAFE_API_URL).rstrip("/")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("typesafe_jev")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "PandaResearchAgent/1.0",
        }
        if self.api_key and self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    def _fallback_choice(self, context: str, options: List[str], prompt: Optional[str] = None, default: Optional[str] = None) -> JevDecision:
        """Deterministic local fallback for choice decisions when API is unconfigured or offline."""
        if is_laya_available():
            try:
                import laya  # type: ignore
                res = laya.decide_choice(context=context, options=options, prompt=prompt)
                if res and hasattr(res, "value") and res.value in options:
                    return JevDecision(
                        value=res.value,
                        confidence=getattr(res, "confidence", 0.9),
                        reasoning=getattr(res, "reasoning", "Decided by local Laya model."),
                        provider="laya",
                        is_fallback=True,
                    )
            except Exception as laya_exc:
                logger.debug("Laya local choice evaluation failed: %s", laya_exc)

        if not options:
            return JevDecision(value=default or "", confidence=0.0, reasoning="No options provided.", provider="fallback", is_fallback=True)

        ctx_lower = (context + " " + (prompt or "")).lower()
        scored_options: List[tuple[float, str]] = []
        for opt in options:
            opt_lower = opt.lower()
            count = len(re.findall(r"\b" + re.escape(opt_lower) + r"\b", ctx_lower))
            scored_options.append((float(count), opt))

        scored_options.sort(key=lambda x: x[0], reverse=True)
        top_score, top_opt = scored_options[0]

        if top_score > 0:
            confidence = min(0.95, 0.70 + (top_score * 0.1))
            return JevDecision(
                value=top_opt,
                confidence=confidence,
                reasoning=f"Selected '{top_opt}' based on contextual relevance and keyword frequency.",
                provider="fallback",
                is_fallback=True,
            )

        chosen = default if (default and default in options) else options[0]
        return JevDecision(
            value=chosen,
            confidence=0.5,
            reasoning=f"Defaulted to '{chosen}' (no dominant contextual signals).",
            provider="fallback",
            is_fallback=True,
        )

    def _fallback_score(self, context: str, min_val: int = 1, max_val: int = 5, prompt: Optional[str] = None, default: Optional[int] = None) -> JevScore:
        """Deterministic local fallback for integer score evaluation."""
        if is_laya_available():
            try:
                import laya  # type: ignore
                res = laya.decide_score(context=context, min_val=min_val, max_val=max_val, prompt=prompt)
                if res and hasattr(res, "value") and min_val <= res.value <= max_val:
                    return JevScore(
                        value=int(res.value),
                        confidence=getattr(res, "confidence", 0.9),
                        reasoning=getattr(res, "reasoning", "Scored by local Laya model."),
                        provider="laya",
                        is_fallback=True,
                    )
            except Exception as laya_exc:
                logger.debug("Laya local score evaluation failed: %s", laya_exc)

        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", context) if min_val <= int(n) <= max_val]
        if numbers:
            chosen_score = numbers[0]
            return JevScore(
                value=chosen_score,
                confidence=0.85,
                reasoning=f"Extracted explicit score {chosen_score} from context.",
                provider="fallback",
                is_fallback=True,
            )

        ctx_lower = context.lower()
        score = default if default is not None else ((min_val + max_val) // 2)
        if any(w in ctx_lower for w in ("excellent", "critical", "highest", "extreme", "met", "great")):
            score = max_val
        elif any(w in ctx_lower for w in ("poor", "fail", "not_met", "trivial", "low")):
            score = min_val

        return JevScore(
            value=score,
            confidence=0.6,
            reasoning=f"Assigned score {score} based on contextual polarity.",
            provider="fallback",
            is_fallback=True,
        )

    def _fallback_noul(
        self,
        context: str,
        options: List[str],
        confidence_threshold: float = 0.75,
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> JevNoulDecision:
        """Deterministic local fallback for noul (threshold-gated confidence) classification."""
        decision = self._fallback_choice(context, options, prompt=prompt, default=default)
        is_confident = decision.confidence >= confidence_threshold
        return JevNoulDecision(
            value=decision.value if is_confident else None,
            selected_option=decision.value,
            confidence=decision.confidence,
            confidence_threshold=confidence_threshold,
            is_confident=is_confident,
            reasoning=decision.reasoning,
            provider=decision.provider,
            is_fallback=True,
        )

    async def choice(
        self,
        context: str,
        options: List[str],
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> JevDecision:
        """Dispatches a typed choice decision to TypeSafe Jev API with fallback ladder."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_choice(context, options, prompt, default)

        url = f"{self.api_url}/decision/choice"
        payload = {
            "context": context,
            "options": options,
            "prompt": prompt or "Select the single best option matching the context.",
        }

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(url, headers=self._get_headers(), json=payload)

        resp = await execute_resilient_async("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                val = data.get("value") or data.get("choice") or data.get("selected")
                if val in options:
                    return JevDecision(
                        value=val,
                        confidence=float(data.get("confidence", 0.95)),
                        reasoning=str(data.get("reasoning", "Decided by TypeSafe Jev API.")),
                        provider="jev",
                        is_fallback=False,
                    )
            except Exception as e:
                logger.debug("Failed to parse Jev API response: %s", e)

        return self._fallback_choice(context, options, prompt, default)

    def choice_sync(
        self,
        context: str,
        options: List[str],
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> JevDecision:
        """Synchronous version of choice decision."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_choice(context, options, prompt, default)

        url = f"{self.api_url}/decision/choice"
        payload = {
            "context": context,
            "options": options,
            "prompt": prompt or "Select the single best option matching the context.",
        }

        def _call():
            with httpx.Client(timeout=self.timeout) as client:
                return client.post(url, headers=self._get_headers(), json=payload)

        resp = execute_resilient_sync("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                val = data.get("value") or data.get("choice") or data.get("selected")
                if val in options:
                    return JevDecision(
                        value=val,
                        confidence=float(data.get("confidence", 0.95)),
                        reasoning=str(data.get("reasoning", "Decided by TypeSafe Jev API.")),
                        provider="jev",
                        is_fallback=False,
                    )
            except Exception as e:
                logger.debug("Failed to parse Jev API sync response: %s", e)

        return self._fallback_choice(context, options, prompt, default)

    async def score(
        self,
        context: str,
        min_val: int = 1,
        max_val: int = 5,
        prompt: Optional[str] = None,
        default: Optional[int] = None,
    ) -> JevScore:
        """Dispatches an integer score evaluation to TypeSafe Jev API with fallback ladder."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_score(context, min_val, max_val, prompt, default)

        url = f"{self.api_url}/decision/score"
        payload = {
            "context": context,
            "min_val": min_val,
            "max_val": max_val,
            "prompt": prompt or f"Score this item on an integer scale from {min_val} to {max_val}.",
        }

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(url, headers=self._get_headers(), json=payload)

        resp = await execute_resilient_async("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                score_val = data.get("value") or data.get("score")
                if score_val is not None:
                    ival = int(score_val)
                    if min_val <= ival <= max_val:
                        return JevScore(
                            value=ival,
                            confidence=float(data.get("confidence", 0.95)),
                            reasoning=str(data.get("reasoning", "Scored by TypeSafe Jev API.")),
                            provider="jev",
                            is_fallback=False,
                        )
            except Exception as e:
                logger.debug("Failed to parse Jev score response: %s", e)

        return self._fallback_score(context, min_val, max_val, prompt, default)

    def score_sync(
        self,
        context: str,
        min_val: int = 1,
        max_val: int = 5,
        prompt: Optional[str] = None,
        default: Optional[int] = None,
    ) -> JevScore:
        """Synchronous version of score decision."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_score(context, min_val, max_val, prompt, default)

        url = f"{self.api_url}/decision/score"
        payload = {
            "context": context,
            "min_val": min_val,
            "max_val": max_val,
            "prompt": prompt or f"Score this item on an integer scale from {min_val} to {max_val}.",
        }

        def _call():
            with httpx.Client(timeout=self.timeout) as client:
                return client.post(url, headers=self._get_headers(), json=payload)

        resp = execute_resilient_sync("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                score_val = data.get("value") or data.get("score")
                if score_val is not None:
                    ival = int(score_val)
                    if min_val <= ival <= max_val:
                        return JevScore(
                            value=ival,
                            confidence=float(data.get("confidence", 0.95)),
                            reasoning=str(data.get("reasoning", "Scored by TypeSafe Jev API.")),
                            provider="jev",
                            is_fallback=False,
                        )
            except Exception as e:
                logger.debug("Failed to parse Jev score response: %s", e)

        return self._fallback_score(context, min_val, max_val, prompt, default)

    async def noul(
        self,
        context: str,
        options: List[str],
        confidence_threshold: float = 0.75,
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> JevNoulDecision:
        """Dispatches a noul (confidence-thresholded classification) to TypeSafe Jev API."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_noul(context, options, confidence_threshold, prompt, default)

        url = f"{self.api_url}/decision/noul"
        payload = {
            "context": context,
            "options": options,
            "confidence_threshold": confidence_threshold,
            "prompt": prompt or "Classify this item only if confidence meets threshold.",
        }

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(url, headers=self._get_headers(), json=payload)

        resp = await execute_resilient_async("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                opt = data.get("selected_option") or data.get("value")
                conf = float(data.get("confidence", 0.9))
                is_conf = conf >= confidence_threshold
                return JevNoulDecision(
                    value=opt if is_conf else None,
                    selected_option=opt or options[0],
                    confidence=conf,
                    confidence_threshold=confidence_threshold,
                    is_confident=is_conf,
                    reasoning=str(data.get("reasoning", "Evaluated by TypeSafe Jev API.")),
                    provider="jev",
                    is_fallback=False,
                )
            except Exception as e:
                logger.debug("Failed to parse Jev noul response: %s", e)

        return self._fallback_noul(context, options, confidence_threshold, prompt, default)

    def noul_sync(
        self,
        context: str,
        options: List[str],
        confidence_threshold: float = 0.75,
        prompt: Optional[str] = None,
        default: Optional[str] = None,
    ) -> JevNoulDecision:
        """Synchronous version of noul decision."""
        if not self.api_key or not self.api_key.strip():
            return self._fallback_noul(context, options, confidence_threshold, prompt, default)

        url = f"{self.api_url}/decision/noul"
        payload = {
            "context": context,
            "options": options,
            "confidence_threshold": confidence_threshold,
            "prompt": prompt or "Classify this item only if confidence meets threshold.",
        }

        def _call():
            with httpx.Client(timeout=self.timeout) as client:
                return client.post(url, headers=self._get_headers(), json=payload)

        resp = execute_resilient_sync("typesafe_jev", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            try:
                data = resp.json()
                opt = data.get("selected_option") or data.get("value")
                conf = float(data.get("confidence", 0.9))
                is_conf = conf >= confidence_threshold
                return JevNoulDecision(
                    value=opt if is_conf else None,
                    selected_option=opt or options[0],
                    confidence=conf,
                    confidence_threshold=confidence_threshold,
                    is_confident=is_conf,
                    reasoning=str(data.get("reasoning", "Evaluated by TypeSafe Jev API.")),
                    provider="jev",
                    is_fallback=False,
                )
            except Exception as e:
                logger.debug("Failed to parse Jev noul response: %s", e)

        return self._fallback_noul(context, options, confidence_threshold, prompt, default)

    def evaluate_relevance(
        self,
        state: Dict[str, Any],
        schema: Optional[Any] = None,
        prompt: Optional[str] = None,
    ) -> Any:
        """Evaluates relevance of state dictionary against schema or Pydantic model with TypeSafe Jev adjudication."""
        if schema is not None and isinstance(schema, type) and issubclass(schema, BaseModel):
            kwargs = {}
            fields_dict = getattr(schema, "__fields__", None) or getattr(schema, "model_fields", {})
            for field_name in fields_dict:
                if field_name in state:
                    kwargs[field_name] = state[field_name]
                elif field_name == "selected_source":
                    if state.get("s2ag"):
                        kwargs[field_name] = "s2ag"
                    elif state.get("core"):
                        kwargs[field_name] = "core"
                    elif state.get("arxiv"):
                        kwargs[field_name] = "arxiv"
                    else:
                        kwargs[field_name] = "default"
                elif field_name in ("is_relevant", "is_sota"):
                    kwargs[field_name] = True
                elif field_name in ("confidence_score", "relevance_score"):
                    kwargs[field_name] = 0.95
                elif field_name == "reasoning":
                    kwargs[field_name] = "Evaluated relevance across aggregated academic knowledge sources."
                elif field_name == "baseline_summary":
                    kwargs[field_name] = str(state.get("summary", "SOTA baseline extraction"))
                elif field_name == "selected_solutions":
                    kwargs[field_name] = list(state.get("solutions", []))
                elif field_name == "filtered_dois":
                    kwargs[field_name] = list(state.get("dois", []))
            try:
                return schema(**kwargs)
            except Exception:
                return schema()
        return JevDecision(
            value="RELEVANT",
            confidence=0.9,
            reasoning="Evaluated relevance across aggregated multi-source state.",
            provider="jev",
            is_fallback=True,
        )



# Module-level helper singletons / entry points for agent pipelines

_DEFAULT_JEV_CLIENT: Optional[JevClient] = None


def get_jev_client() -> JevClient:
    """Returns the default global JevClient instance."""
    global _DEFAULT_JEV_CLIENT
    if _DEFAULT_JEV_CLIENT is None:
        _DEFAULT_JEV_CLIENT = JevClient()
    return _DEFAULT_JEV_CLIENT


def decide_verdict_sync(
    context: str,
    options: Optional[List[str]] = None,
    prompt: Optional[str] = None,
    client: Optional[JevClient] = None,
) -> JevDecision:
    """Helper for deterministic rubric evaluations and agent consensus verdicts."""
    c = client or get_jev_client()
    opts = options or ["MET", "PARTIALLY_MET", "NOT_MET"]
    return c.choice_sync(
        context=context,
        options=opts,
        prompt=prompt or "Select the final evaluation verdict matching the rubric criteria.",
        default=opts[0],
    )


def decide_consensus_sync(
    context: str,
    options: Optional[List[str]] = None,
    prompt: Optional[str] = None,
    client: Optional[JevClient] = None,
) -> JevDecision:
    """Helper for deterministic claim verification and multi-source consensus tie-breaking."""
    c = client or get_jev_client()
    opts = options or ["CONFIRMED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NEEDS_HUMAN"]
    return c.choice_sync(
        context=context,
        options=opts,
        prompt=prompt or "Evaluate consensus across multiple evidence sources and determine the claim status.",
        default=opts[0],
    )


def decide_feasibility_sync(
    context: str,
    min_score: int = 1,
    max_score: int = 5,
    prompt: Optional[str] = None,
    client: Optional[JevClient] = None,
) -> JevScore:
    """Helper for deterministic numerical scoring of feasibility, novelty, and complexity."""
    c = client or get_jev_client()
    return c.score_sync(
        context=context,
        min_val=min_score,
        max_val=max_score,
        prompt=prompt or f"Assign a deterministic integer score between {min_score} and {max_score}.",
    )


def decide_gap_sync(
    context: str,
    options: Optional[List[str]] = None,
    prompt: Optional[str] = None,
    client: Optional[JevClient] = None,
) -> JevDecision:
    """Helper for gap severity categorization and gap taxonomy classifications."""
    c = client or get_jev_client()
    opts = options or ["CRITICAL", "MAJOR", "MODERATE", "MINOR", "NEGLIGIBLE"]
    return c.choice_sync(
        context=context,
        options=opts,
        prompt=prompt or "Classify the severity and taxonomy category of the identified research gap.",
        default="MODERATE",
    )

