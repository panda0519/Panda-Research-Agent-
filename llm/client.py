"""LLM client wrapper for unified Anthropic API and token tracking.

Reads configuration from llm/models.yaml, manages API calls, tracks token usage
and costs, and provides fallback / mock capabilities.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

# Ensure .env is loaded on startup
load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")


def extract_json(text: str) -> Any:
    text = text.strip()
    # strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    # fall back to grabbing the first {...} or [...] block if there's
    # leading/trailing prose around it
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        text = match.group(1)
    # Repair stray backslashes that aren't valid JSON escapes
    # (e.g. Windows paths, regex, LaTeX the LLM didn't double-escape)
    text = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', text)
    return json.loads(text)

logger = logging.getLogger(__name__)

MODELS_YAML_PATH = Path(__file__).parent / "models.yaml"


def load_model_config() -> Dict[str, Any]:
    if MODELS_YAML_PATH.exists():
        with open(MODELS_YAML_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# Cost per million tokens in USD
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-3-7-sonnet-20250219": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0},
    "claude-haiku-3.5": {"input": 0.8, "output": 4.0},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
}


class LLMClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key
        self.config = load_model_config()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self._client: Any = None

    @property
    def api_key(self) -> str:
        return self._api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value
        self._client = None


    @property
    def client(self) -> Any:
        if self._client is None and self.api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except Exception as e:
                logger.warning("Could not initialize Anthropic client: %s", e)
        return self._client

    def get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        agents_cfg = self.config.get("agents", {})
        cfg = agents_cfg.get(agent_name, {})
        default_model = self.config.get("default_model", "claude-sonnet-5")
        return {
            "model": cfg.get("model", default_model),
            "temperature": cfg.get("temperature", 0.3),
            "search_backends": cfg.get("search_backends", ["claude_web_search", "tavily"]),
        }

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Call primary LLM provider with automatic multi-provider fallback."""
        load_dotenv()
        preferred = os.getenv("LLM_PROVIDER", LLM_PROVIDER).lower()
        has_gemini = bool(os.getenv("GEMINI_API_KEY"))
        has_anthropic = bool(self.api_key or os.getenv("ANTHROPIC_API_KEY"))

        if preferred == "anthropic":
            providers = ["anthropic", "gemini"]
        else:
            providers = ["gemini", "anthropic"]

        last_error: Optional[Exception] = None

        for provider in providers:
            if provider == "gemini" and has_gemini:
                try:
                    return self._generate_gemini(prompt, system_prompt, model, temperature, max_tokens)
                except Exception as exc:
                    logger.warning("Gemini LLM generation failed, attempting fallback: %s", exc)
                    last_error = exc
            elif provider == "anthropic" and has_anthropic:
                try:
                    return self._generate_anthropic(prompt, system_prompt, model, temperature, max_tokens, tools)
                except Exception as exc:
                    logger.warning("Anthropic LLM generation failed, attempting fallback: %s", exc)
                    last_error = exc

        if last_error is not None:
            logger.error("All available LLM providers failed. Last error: %s", last_error)
            raise last_error

        logger.warning("No valid LLM API key configured (GEMINI_API_KEY / ANTHROPIC_API_KEY); returning simulated mock response.")
        return f"[Simulated response for: {prompt[:80]}...]"

    def _generate_gemini(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        gemini_client = genai.Client(api_key=api_key)
        gemini_model_name = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
        if model and ("gemini" in model.lower() or "models/" in model.lower()):
            gemini_model_name = model

        config_kwargs: Dict[str, Any] = {}
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if max_tokens:
            config_kwargs["max_output_tokens"] = max(max_tokens, 1024)
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        response = gemini_client.models.generate_content(
            model=gemini_model_name,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
        )
        return response.text or ""

    def _generate_anthropic(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        target_model = model or self.config.get("default_model", "claude-3-5-sonnet-20241022")
        if target_model == "claude-sonnet-5":
            target_model = "claude-3-5-sonnet-20241022"

        if not self.api_key or not self.client:
            raise ValueError("ANTHROPIC_API_KEY not configured.")

        kwargs: Dict[str, Any] = {
            "model": target_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            kwargs["extra_body"] = {"temperature": temperature}
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        usage = getattr(response, "usage", None)
        if usage:
            in_tok = getattr(usage, "input_tokens", 0)
            out_tok = getattr(usage, "output_tokens", 0)
            self.total_input_tokens += in_tok
            self.total_output_tokens += out_tok

            pricing = MODEL_PRICING.get(target_model, {"input": 3.0, "output": 15.0})
            cost = (in_tok * pricing["input"] + out_tok * pricing["output"]) / 1_000_000
            self.total_cost_usd += cost

        content_blocks = getattr(response, "content", [])
        text_blocks = [b.text for b in content_blocks if getattr(b, "type", "") == "text"]
        return "\n".join(text_blocks)


# Global instance
default_llm_client = LLMClient()
