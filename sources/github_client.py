"""GitHub REST API client for repository health inspection and dependency validation."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from sources.resilience import CircuitBreaker, execute_resilient_async, get_circuit_breaker

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class GitHubRepoHealth:
    owner: str
    repo: str
    full_name: str
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    subscribers_count: int = 0
    is_archived: bool = False
    is_fork: bool = False
    default_branch: str = "main"
    pushed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    license_spdx: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    is_authenticated: bool = False


class GitHubClient:
    token: Optional[str] = None
    timeout: float = 10.0

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 10.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self.timeout = timeout
        self.circuit_breaker = circuit_breaker or get_circuit_breaker("github")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PandaResearchAgent/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token and self.token.strip():
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        return headers

    @staticmethod
    def parse_repo_identifier(identifier: str) -> Optional[tuple[str, str]]:
        """Parses 'owner/repo' or 'https://github.com/owner/repo' into (owner, repo)."""
        clean = identifier.strip().rstrip("/")
        # Match URL pattern
        url_match = re.search(r"github\.com/([^/]+)/([^/]+)", clean, re.IGNORECASE)
        if url_match:
            owner, repo = url_match.group(1), url_match.group(2)
            if repo.endswith(".git"):
                repo = repo[:-4]
            return owner, repo

        # Match owner/repo pattern
        parts = clean.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            repo = parts[1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            return parts[0], repo

        return None

    async def get_repo_health(self, owner_or_identifier: str, repo_name: Optional[str] = None) -> Optional[GitHubRepoHealth]:
        """Fetches repository health metrics for a given owner/repo."""
        if repo_name is not None:
            owner, repo = owner_or_identifier.strip(), repo_name.strip()
        else:
            parsed = self.parse_repo_identifier(owner_or_identifier)
            if not parsed:
                logger.debug("Invalid GitHub repository identifier: %s", owner_or_identifier)
                return None
            owner, repo = parsed

        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        headers = self._get_headers()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, headers=headers)

        resp = await execute_resilient_async("github", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            license_info = data.get("license") or {}
            spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
            return GitHubRepoHealth(
                owner=data.get("owner", {}).get("login", owner),
                repo=data.get("name", repo),
                full_name=data.get("full_name", f"{owner}/{repo}"),
                stars=data.get("stargazers_count", 0),
                forks=data.get("forks_count", 0),
                open_issues=data.get("open_issues_count", 0),
                subscribers_count=data.get("subscribers_count", 0),
                is_archived=data.get("archived", False),
                is_fork=data.get("fork", False),
                default_branch=data.get("default_branch", "main"),
                pushed_at=data.get("pushed_at"),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
                license_spdx=spdx if spdx != "NOASSERTION" else None,
                description=data.get("description"),
                language=data.get("language"),
                topics=data.get("topics", []),
                is_authenticated=bool(self.token and self.token.strip()),
            )
        elif resp and getattr(resp, "status_code", 0) == 404:
            logger.debug("Repository not found: %s/%s", owner, repo)
            return None
        return None

    async def search_repositories(self, query: str, limit: int = 5) -> List[GitHubRepoHealth]:
        """Searches GitHub repositories by keyword."""
        if not query or not query.strip():
            return []

        url = f"{GITHUB_API_BASE}/search/repositories"
        params = {"q": query.strip(), "per_page": min(limit, 10), "sort": "stars", "order": "desc"}
        headers = self._get_headers()

        async def _call():
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                return await client.get(url, params=params, headers=headers)

        resp = await execute_resilient_async("github", _call, circuit_breaker=self.circuit_breaker)
        if resp and getattr(resp, "status_code", 0) == 200:
            data = resp.json()
            results: List[GitHubRepoHealth] = []
            for item in data.get("items", [])[:limit]:
                license_info = item.get("license") or {}
                spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
                results.append(
                    GitHubRepoHealth(
                        owner=item.get("owner", {}).get("login", ""),
                        repo=item.get("name", ""),
                        full_name=item.get("full_name", ""),
                        stars=item.get("stargazers_count", 0),
                        forks=item.get("forks_count", 0),
                        open_issues=item.get("open_issues_count", 0),
                        subscribers_count=item.get("subscribers_count", 0),
                        is_archived=item.get("archived", False),
                        is_fork=item.get("fork", False),
                        default_branch=item.get("default_branch", "main"),
                        pushed_at=item.get("pushed_at"),
                        created_at=item.get("created_at"),
                        updated_at=item.get("updated_at"),
                        license_spdx=spdx if spdx != "NOASSERTION" else None,
                        description=item.get("description"),
                        language=item.get("language"),
                        topics=item.get("topics", []),
                        is_authenticated=bool(self.token and self.token.strip()),
                    )
                )
            return results
        return []

        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        headers = self._get_headers()

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        license_info = data.get("license") or {}
                        spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
                        return GitHubRepoHealth(
                            owner=data.get("owner", {}).get("login", owner),
                            repo=data.get("name", repo),
                            full_name=data.get("full_name", f"{owner}/{repo}"),
                            stars=data.get("stargazers_count", 0),
                            forks=data.get("forks_count", 0),
                            open_issues=data.get("open_issues_count", 0),
                            subscribers_count=data.get("subscribers_count", 0),
                            is_archived=data.get("archived", False),
                            is_fork=data.get("fork", False),
                            default_branch=data.get("default_branch", "main"),
                            pushed_at=data.get("pushed_at"),
                            created_at=data.get("created_at"),
                            updated_at=data.get("updated_at"),
                            license_spdx=spdx if spdx != "NOASSERTION" else None,
                            description=data.get("description"),
                            language=data.get("language"),
                            topics=data.get("topics", []),
                            is_authenticated=bool(self.token and self.token.strip()),
                        )
                    elif resp.status_code == 404:
                        logger.debug("GitHub repository not found: %s/%s", owner, repo)
                        return None
                    elif resp.status_code in (403, 429):
                        logger.warning("GitHub API rate limit encountered (status %d)", resp.status_code)
                        if attempt == 0:
                            await asyncio.sleep(1.0)
                            continue
                        return None
                    else:
                        logger.debug("GitHub API returned status %d for %s/%s", resp.status_code, owner, repo)
                        return None
            except httpx.TimeoutException:
                logger.warning("GitHub API timed out for %s/%s", owner, repo)
                return None
            except Exception as exc:
                logger.warning("GitHub API request failed for %s/%s: %s", owner, repo, exc)
                return None
        return None

    async def search_repositories(self, query: str, limit: int = 5) -> List[GitHubRepoHealth]:
        """Searches GitHub repositories by keyword."""
        if not query or not query.strip():
            return []

        url = f"{GITHUB_API_BASE}/search/repositories"
        params = {"q": query.strip(), "per_page": min(limit, 10), "sort": "stars", "order": "desc"}
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    results: List[GitHubRepoHealth] = []
                    for item in data.get("items", [])[:limit]:
                        license_info = item.get("license") or {}
                        spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
                        results.append(
                            GitHubRepoHealth(
                                owner=item.get("owner", {}).get("login", ""),
                                repo=item.get("name", ""),
                                full_name=item.get("full_name", ""),
                                stars=item.get("stargazers_count", 0),
                                forks=item.get("forks_count", 0),
                                open_issues=item.get("open_issues_count", 0),
                                subscribers_count=item.get("subscribers_count", 0),
                                is_archived=item.get("archived", False),
                                is_fork=item.get("fork", False),
                                default_branch=item.get("default_branch", "main"),
                                pushed_at=item.get("pushed_at"),
                                created_at=item.get("created_at"),
                                updated_at=item.get("updated_at"),
                                license_spdx=spdx if spdx != "NOASSERTION" else None,
                                description=item.get("description"),
                                language=item.get("language"),
                                topics=item.get("topics", []),
                                is_authenticated=bool(self.token and self.token.strip()),
                            )
                        )
                    return results
                return []
        except Exception as exc:
            logger.warning("GitHub search failed for %s: %s", query, exc)
            return []


async def fetch_repo_health(repo_or_url: str, token: Optional[str] = None) -> Optional[GitHubRepoHealth]:
    """Helper function to fetch repository health with default client."""
    client = GitHubClient(token=token)
    return await client.get_repo_health(repo_or_url)
