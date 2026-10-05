"""TechStackAgent: recommends tailored technology stack across architecture layers with live GitHub health verification."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard, TechStackRecommendation
from message import MessageBus, MessageType
from sources.github_client import GitHubClient, GitHubRepoHealth

logger = logging.getLogger(__name__)


class TechStackAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 5,
        llm_client: Optional[Any] = None,
        github_client: Optional[GitHubClient] = None,
    ) -> None:
        super().__init__(
            name="TechStackAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.github = github_client or GitHubClient()

    async def _run(self) -> List[TechStackRecommendation]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        features_summary = "\n".join([f"- {f.title}: {f.description}" for f in self.blackboard.proposed_features])

        prompt = f"""You are a principal systems architect.
Recommend a practical, modern technology stack tailored for:
Topic: {topic}
Project Context: {context}

PROPOSED FEATURES & REQUIREMENTS:
{features_summary or 'Standard production system'}

Provide recommendations across 5 key architectural layers:
1. "frontend": UI / client interface (e.g. Next.js, React, SwiftUI, Flutter, Streamlit)
2. "backend": API & business logic server (e.g. FastAPI, Go Gin, Node/Express)
3. "ai_orchestration": ML/LLM inference & agent orchestration (e.g. ONNX Runtime, Anthropic SDK, PyTorch)
4. "data_storage": relational, vector, or cache databases (e.g. PostgreSQL, SQLite, Qdrant, Redis)
5. "infrastructure": deployment, containerization, observability (e.g. Docker, Fly.io, AWS ECS, Prometheus)

For each layer, return:
- layer: string
- selected_tech: string (specific technology and framework)
- alternatives_considered: list of strings (competitors/alternatives)
- rationale: concise justification explaining performance, latency, maintenance trade-offs

Return ONLY a JSON array of objects.
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "claude-sonnet-5"),
                temperature=self.config.get("temperature", 0.3),
            )
            data = self.parse_json_response(raw_text)
            recommendations: List[TechStackRecommendation] = []
            for item in data:
                if isinstance(item, dict) and "layer" in item:
                    selected_tech = str(item.get("selected_tech", "")).strip()
                    rec = TechStackRecommendation(
                        layer=str(item.get("layer", "")).strip(),
                        selected_tech=selected_tech,
                        alternatives_considered=item.get("alternatives_considered", []),
                        rationale=str(item.get("rationale", "")).strip(),
                    )

                    # Enrich with GitHub repo health verification if applicable
                    try:
                        health = await self._check_tech_repo_health(selected_tech)
                        if health:
                            rec.repo_url = f"https://github.com/{health.full_name}"
                            rec.stars = health.stars
                            rec.forks = health.forks
                            rec.open_issues = health.open_issues
                            rec.license = health.license_spdx
                            rec.is_archived = health.is_archived
                            rec.last_pushed_at = health.pushed_at
                            if health.is_archived:
                                rec.health_notes = "⚠️ Repository is archived on GitHub. Consider actively maintained alternatives."
                                logger.warning("Recommended technology '%s' is archived on GitHub (%s)", selected_tech, health.full_name)
                            else:
                                rec.health_notes = f"⭐ {health.stars:,} stars | 🍴 {health.forks:,} forks | License: {health.license_spdx or 'Unspecified'}"
                    except Exception as gh_exc:
                        logger.debug("GitHub health check skipped for '%s': %s", selected_tech, gh_exc)

                    self.blackboard.add_tech_stack_item(rec)
                    recommendations.append(rec)

            # Record provenance on Blackboard metadata
            has_gh = any(r.repo_url and "github.com" in r.repo_url for r in recommendations)
            if has_gh:
                self.blackboard.metadata["github_access_mode"] = "authenticated" if getattr(self.github, "token", None) else "unauthenticated"
            else:
                self.blackboard.metadata["github_access_mode"] = "baseline"

            self.send_message(
                recipient="*",
                msg_type=MessageType.TECH_STACK_PROPOSED,
                payload={"count": len(recommendations), "layers": [r.layer for r in recommendations]},
            )
            return recommendations
        except Exception as exc:
            logger.error("TechStackAgent failed: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            return []

    async def _check_tech_repo_health(self, tech_name: str) -> Optional[GitHubRepoHealth]:
        """Queries GitHub for repository health using owner/repo lookup or search."""
        if not tech_name or not tech_name.strip():
            return None

        # 1. Direct owner/repo identifier lookup
        parsed = GitHubClient.parse_repo_identifier(tech_name)
        if parsed:
            return await self.github.get_repo_health(parsed[0], parsed[1])

        # 2. Search by tech name
        search_res = await self.github.search_repositories(tech_name, limit=1)
        if search_res:
            return search_res[0]
        return None
