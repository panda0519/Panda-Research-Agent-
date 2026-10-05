"""API Key management utilities: masking, atomic .env edits, and scoped runtime injection."""
from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import httpx

logger = logging.getLogger(__name__)

# Key metadata definitions matching README.md descriptions and 5 specialization tiers
KEY_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # Core reasoning, web search & vector memory
    "ANTHROPIC_API_KEY": {
        "name": "Anthropic Claude",
        "env_var": "ANTHROPIC_API_KEY",
        "description": "Anthropic Claude SDK (core reasoning & search)",
        "docs_url": "https://console.anthropic.com/",
        "is_secret": True,
        "category": "Core LLM & Search",
    },
    "GEMINI_API_KEY": {
        "name": "Google Gemini",
        "env_var": "GEMINI_API_KEY",
        "description": "Google Gemini API (synthesis & grounding)",
        "docs_url": "https://aistudio.google.com/",
        "is_secret": True,
        "category": "Core LLM & Search",
    },
    "TAVILY_API_KEY": {
        "name": "Tavily Search",
        "env_var": "TAVILY_API_KEY",
        "description": "Tavily Search API (multi-engine web search)",
        "docs_url": "https://tavily.com/",
        "is_secret": True,
        "category": "Core LLM & Search",
    },
    "VOYAGE_API_KEY": {
        "name": "Voyage AI",
        "env_var": "VOYAGE_API_KEY",
        "description": "Voyage AI (cross-run vector memory embeddings)",
        "docs_url": "https://dash.voyageai.com/",
        "is_secret": True,
        "category": "Vector Memory",
    },
    # Specialization 1: Repo Health (TechStackAgent)
    "GITHUB_TOKEN": {
        "name": "GitHub Personal Access Token",
        "env_var": "GITHUB_TOKEN",
        "description": "GitHub REST API (repository health & dependency metrics; optional for higher rate limits)",
        "docs_url": "https://github.com/settings/tokens",
        "is_secret": True,
        "category": "Repository Health",
    },
    # Specialization 2: Academic Full Text (PaperReaderAgent)
    "UNPAYWALL_EMAIL": {
        "name": "Unpaywall Contact Email",
        "env_var": "UNPAYWALL_EMAIL",
        "description": "Unpaywall API (Open Access PDF resolution & paper metadata; non-secret email)",
        "docs_url": "https://unpaywall.org/products/api",
        "is_secret": False,
        "placeholder": "researcher@example.com",
        "category": "Academic Full Text",
    },
    "CORE_API_KEY": {
        "name": "CORE Academic API",
        "env_var": "CORE_API_KEY",
        "description": "CORE API (global research repository search & full-text extraction)",
        "docs_url": "https://core.ac.uk/services/api",
        "is_secret": True,
        "category": "Academic Full Text",
    },
    # Specialization 3: Second-Model Claim Check (Layer 2 Verification)
    "GROQ_API_KEY": {
        "name": "Groq Cloud API",
        "env_var": "GROQ_API_KEY",
        "description": "Groq Cloud API (ultra-fast secondary LLM claim verification & cross-checking)",
        "docs_url": "https://console.groq.com/keys",
        "is_secret": True,
        "category": "Second-Model Verification",
    },
    # Specialization 4: Broader Academic Search (Surveyor & GapAnalyst)
    "OPENALEX_API_KEY": {
        "name": "OpenAlex API",
        "env_var": "OPENALEX_API_KEY",
        "description": "OpenAlex API (scholarly graph discovery & citation tracking; optional for higher throughput)",
        "docs_url": "https://openalex.org/",
        "is_secret": True,
        "category": "Broader Academic Search",
    },
    "CROSSREF_MAILTO": {
        "name": "Crossref Polite Pool Email",
        "env_var": "CROSSREF_MAILTO",
        "description": "Crossref API (DOI registry & publication metadata polite pool; non-secret email)",
        "docs_url": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
        "is_secret": False,
        "placeholder": "researcher@example.com",
        "category": "Broader Academic Search",
    },
    # Specialization 5: Computational Claim Check (Layer 2 & 3 Verification)
    "WOLFRAM_APP_ID": {
        "name": "Wolfram Alpha App ID",
        "env_var": "WOLFRAM_APP_ID",
        "description": "Wolfram Alpha API (authoritative mathematical & scientific computation; 5 calls/run cap)",
        "docs_url": "https://developer.wolframalpha.com/portal/myapps/",
        "is_secret": True,
        "category": "Computational Verification",
    },
    # Typed Decision Layer (TypeSafe Jev & Laya Backup)
    "TYPESAFE_API_KEY": {
        "name": "TypeSafe Jev API",
        "env_var": "TYPESAFE_API_KEY",
        "description": "TypeSafe Jev API (deterministic typed decision layer: choice, score, & noul tie-breaks)",
        "docs_url": "https://typesafe.ai/",
        "is_secret": True,
        "category": "Typed Decision Layer",
    },
}


def mask_api_key(key: Optional[str], is_secret: bool = True) -> str:
    """Masks an API key for safe UI display.

    Rules:
    - If is_secret is False (e.g. email addresses), returns the plain value.
    - Empty string -> empty string
    - <= 8 characters -> completely masked ('•' * length)
    - > 8 characters -> at most 6 prefix characters, 6 dots, and 4 suffix characters.
    """
    if not key:
        return ""
    if not is_secret:
        return key.strip()
    if len(key) <= 8:
        return "•" * len(key)
    if len(key) <= 12:
        prefix_len = min(4, len(key) // 3)
        suffix_len = min(3, len(key) // 3)
        return f"{key[:prefix_len]}{'•' * 6}{key[-suffix_len:]}"
    return f"{key[:6]}{'•' * 6}{key[-4:]}"


def is_env_in_gitignore(repo_root: Union[str, Path] = ".") -> bool:
    """Verifies that .env is explicitly listed and ignored in .gitignore."""
    root = Path(repo_root)
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        return False
    try:
        content = gitignore_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines()]
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if line in (".env", "/.env", "*.env", ".env*") or line.startswith(".env"):
                return True
        return False
    except Exception as exc:
        logger.error("Failed to read .gitignore: %s", exc)
        return False


def get_env_file_keys(env_path: Union[str, Path] = ".env") -> Dict[str, str]:
    """Reads key-value pairs currently stored in the .env file."""
    path = Path(env_path)
    if not path.exists():
        return {}
    keys: Dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            if "=" in line_str:
                parts = line_str.split("=", 1)
                k = parts[0].strip()
                if k.startswith("export "):
                    k = k[7:].strip()
                v = parts[1].strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                keys[k] = v
    except Exception as exc:
        logger.error("Failed to parse .env file: %s", exc)
    return keys


def save_keys_to_env(
    env_path: Union[str, Path],
    updates: Dict[str, str],
    repo_root: Union[str, Path] = ".",
) -> None:
    """Surgically and atomically updates or appends keys in .env.

    Preserves comments, ordering, and blank lines.
    Ensures .env is ignored in .gitignore prior to writing.
    """
    if not is_env_in_gitignore(repo_root):
        raise PermissionError(
            "Security Check Failed: '.env' is not listed in .gitignore. Refusing to write to disk."
        )

    target_path = Path(env_path)
    lines: List[str] = []
    if target_path.exists():
        lines = target_path.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            prefix_part = stripped.split("=", 1)[0].strip()
            var_name = prefix_part[7:].strip() if prefix_part.startswith("export ") else prefix_part
            if var_name in updates:
                new_val = updates[var_name]
                new_lines.append(f"{var_name}={new_val}")
                updated_keys.add(var_name)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated_keys:
            if new_lines and new_lines[-1].strip() != "":
                new_lines.append("")
            new_lines.append(f"{k}={v}")

    parent_dir = target_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        dir=parent_dir,
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    try:
        content_to_write = "\n".join(new_lines)
        if content_to_write and not content_to_write.endswith("\n"):
            content_to_write += "\n"
        temp_file.write(content_to_write)
        temp_file.flush()
        temp_file.close()
        os.replace(temp_path, target_path)
    finally:
        if temp_path.exists():
            with contextlib.suppress(Exception):
                os.unlink(temp_path)


def remove_key_from_env(
    env_path: Union[str, Path],
    key_to_remove: str,
    repo_root: Union[str, Path] = ".",
) -> None:
    """Surgically removes a single key from .env while preserving formatting."""
    if not is_env_in_gitignore(repo_root):
        raise PermissionError(
            "Security Check Failed: '.env' is not listed in .gitignore. Refusing to write to disk."
        )

    target_path = Path(env_path)
    if not target_path.exists():
        return

    lines = target_path.read_text(encoding="utf-8").splitlines()
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            prefix_part = stripped.split("=", 1)[0].strip()
            var_name = prefix_part[7:].strip() if prefix_part.startswith("export ") else prefix_part
            if var_name == key_to_remove:
                continue
        new_lines.append(line)

    parent_dir = target_path.parent
    temp_file = tempfile.NamedTemporaryFile(
        dir=parent_dir,
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    try:
        content_to_write = "\n".join(new_lines)
        if content_to_write and not content_to_write.endswith("\n"):
            content_to_write += "\n"
        temp_file.write(content_to_write)
        temp_file.flush()
        temp_file.close()
        os.replace(temp_path, target_path)
    finally:
        if temp_path.exists():
            with contextlib.suppress(Exception):
                os.unlink(temp_path)


@contextlib.contextmanager
def scoped_env_override(overrides: Dict[str, str]) -> Iterator[None]:
    """Temporarily injects environment variables for the scope of a code block.

    Restores previous values or removes newly added variables in a finally block.
    """
    saved_state: Dict[str, Optional[str]] = {}
    try:
        for k, v in overrides.items():
            if v is not None and v != "":
                saved_state[k] = os.environ.get(k)
                os.environ[k] = v
        yield
    finally:
        for k, old_val in saved_state.items():
            if old_val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_val


def test_key_connection(
    key_name: str,
    key_value: str,
    timeout: float = 10.0,
) -> Tuple[bool, Optional[int], str]:
    """Performs a lightweight connectivity test for a given API key.

    Security Guarantee: Never logs, stores, or returns raw HTTP response bodies.
    Returns (success, status_code, status_message).
    """
    if not key_value or not key_value.strip():
        return False, None, "No API key provided."

    clean_key = key_value.strip()

    try:
        if key_name == "ANTHROPIC_API_KEY":
            url = "https://api.anthropic.com/v1/models"
            headers = {
                "x-api-key": clean_key,
                "anthropic-version": "2023-06-01",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "GEMINI_API_KEY":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={clean_key}"
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (400, 401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "TAVILY_API_KEY":
            url = "https://api.tavily.com/search"
            payload = {"api_key": clean_key, "query": "ping", "max_results": 1}
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "VOYAGE_API_KEY":
            url = "https://api.voyageai.com/v1/embeddings"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "Content-Type": "application/json",
            }
            payload = {"input": ["ping"], "model": "voyage-3-lite"}
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "GITHUB_TOKEN":
            url = "https://api.github.com/user"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "PandaResearchAgent/1.0",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK — Authenticated)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "UNPAYWALL_EMAIL":
            if "@" not in clean_key or "." not in clean_key.split("@")[-1]:
                return False, 400, "Invalid email address format."
            url = f"https://api.unpaywall.org/v2/10.1038/nature12373?email={clean_key}"
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK — Unpaywall Active)"
                if resp.status_code in (422, 400):
                    return False, resp.status_code, f"Invalid email rejected by Unpaywall (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "CORE_API_KEY":
            url = "https://api.core.ac.uk/v3/search/works"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "Accept": "application/json",
                "User-Agent": "PandaResearchAgent/1.0",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers, params={"q": "test", "limit": 1})
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "GROQ_API_KEY":
            url = "https://api.groq.com/openai/v1/models"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "User-Agent": "PandaResearchAgent/1.0",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "OPENALEX_API_KEY":
            url = "https://api.openalex.org/works"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "User-Agent": "PandaResearchAgent/1.0",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers, params={"search": "test", "per_page": 1})
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "CROSSREF_MAILTO":
            if "@" not in clean_key or "." not in clean_key.split("@")[-1]:
                return False, 400, "Invalid email address format."
            url = "https://api.crossref.org/works"
            headers = {"User-Agent": f"PandaResearchAgent/1.0 (mailto:{clean_key})"}
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers, params={"query": "test", "rows": 1, "mailto": clean_key})
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK — Crossref Polite Pool Active)"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "WOLFRAM_APP_ID":
            url = "https://api.wolframalpha.com/v1/result"
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, params={"appid": clean_key, "i": "2+2"})
                if resp.status_code == 200:
                    return True, 200, "Connection successful (HTTP 200 OK — Computation Verified)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        elif key_name == "TYPESAFE_API_KEY":
            url = os.environ.get("TYPESAFE_API_URL", "https://api.typesafe.ai/v1").rstrip("/") + "/health"
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "User-Agent": "PandaResearchAgent/1.0",
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code in (200, 204):
                    return True, resp.status_code, "Connection successful (HTTP 200 OK — TypeSafe Jev Active)"
                if resp.status_code in (401, 403):
                    return False, resp.status_code, f"Authentication failed (HTTP {resp.status_code})"
                return False, resp.status_code, f"Unexpected response (HTTP {resp.status_code})"

        return False, None, f"Unknown key provider: {key_name}"

    except httpx.TimeoutException:
        return False, None, "Connection timed out (10s limit exceeded)"
    except httpx.RequestError as exc:
        return False, None, f"Network request error: {type(exc).__name__}"
    except Exception as exc:
        return False, None, f"Connection test failed: {type(exc).__name__}"
