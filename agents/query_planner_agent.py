"""QueryPlannerAgent: decomposes research topics into multi-angle web and academic search queries."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard
from message import MessageBus, MessageType

logger = logging.getLogger(__name__)


class QueryPlannerAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 0,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name="QueryPlannerAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )

    async def _run(self) -> Dict[str, Any]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        logger.info("QueryPlannerAgent decomposing topic (%d chars)...", len(topic))

        prompt = f"""You are a Principal AI Research Scientist and Search Architect.
Decompose the following research problem into a deep, multi-angle search query plan.

Topic / Problem:
{topic}

Additional Context / Constraints:
{context or 'None provided'}

Generate a comprehensive search plan containing:
1. canonical_topic: A concise, highly accurate title (5-10 words) capturing the core technical subject.
2. domain_taxonomy: A list of 3-6 specific academic / engineering sub-disciplines.
3. core_challenges: A list of 3-5 specific technical bottlenecks or questions that must be investigated.
4. web_queries: A list of 8 to 12 distinct, targeted search queries for web engines.
5. academic_queries: A list of 8 to 12 concise academic search queries (2 to 5 keywords each, NO long sentences) formatted specifically for arXiv and Semantic Scholar APIs.

Return ONLY a JSON object with keys:
"canonical_topic", "domain_taxonomy", "core_challenges", "web_queries", "academic_queries"
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "gemini-2.5-flash"),
                temperature=0.2,
            )
            data = self.parse_json_response(raw_text)
            if isinstance(data, dict) and data.get("web_queries") and data.get("academic_queries"):
                plan = self._sanitize_plan(data, topic)
            else:
                plan = self._build_deterministic_plan(topic, context)
        except Exception as exc:
            logger.warning("QueryPlannerAgent LLM generation failed (%s); using deterministic query synthesis.", exc)
            plan = self._build_deterministic_plan(topic, context)

        self.blackboard.metadata["query_plan"] = plan
        if plan.get("canonical_topic"):
            self.blackboard.metadata["canonical_topic"] = plan["canonical_topic"]

        self.send_message(
            recipient="*",
            msg_type=MessageType.INFO,
            payload={"query_plan": plan},
        )
        return plan

    def _sanitize_plan(self, data: Dict[str, Any], fallback_topic: str) -> Dict[str, Any]:
        canonical = str(data.get("canonical_topic", "")).strip() or fallback_topic[:100]
        taxonomy = [str(x).strip() for x in data.get("domain_taxonomy", []) if str(x).strip()]
        challenges = [str(x).strip() for x in data.get("core_challenges", []) if str(x).strip()]
        web_queries = [str(x).strip() for x in data.get("web_queries", []) if str(x).strip()]
        acad_queries = [self._clean_academic_query(str(x)) for x in data.get("academic_queries", []) if str(x).strip()]
        acad_queries = [q for q in acad_queries if q]

        if not web_queries:
            web_queries = [f"{canonical} architecture", f"{canonical} state of the art benchmark"]
        if not acad_queries:
            acad_queries = [self._clean_academic_query(canonical), f"{canonical} deep learning"]

        return {
            "canonical_topic": canonical,
            "domain_taxonomy": taxonomy or ["Artificial Intelligence", "Systems Engineering"],
            "core_challenges": challenges or ["Scalability", "Architectural Complexity"],
            "web_queries": web_queries,
            "academic_queries": acad_queries,
        }

    def _clean_academic_query(self, query: str) -> str:
        """Strips punctuation and restricts to 2-6 core keywords for arXiv/S2 REST APIs."""
        clean = re.sub(r"[^\w\s-]", " ", query)
        words = [w.strip() for w in clean.split() if len(w.strip()) > 2]
        stops = {"what", "how", "why", "when", "the", "and", "for", "with", "from", "that", "this", "about", "using", "into", "across"}
        filtered = [w for w in words if w.lower() not in stops]
        return " ".join(filtered[:6])

    def _build_deterministic_plan(self, topic: str, context: str) -> Dict[str, Any]:
        """High-precision heuristic query generation when LLM is unavailable."""
        first_line = topic.splitlines()[0].strip() if topic else "AI Research"
        words = [w for w in re.findall(r"\b[A-Za-z0-9_-]{3,}\b", first_line) if w.lower() not in {"the", "and", "for", "with", "this", "that"}]
        core_phrase = " ".join(words[:5]) if words else "emerging AI architecture"

        canonical = first_line[:80].strip() or core_phrase

        web_queries = [
            f"{canonical} state of the art architecture",
            f"{canonical} github open source implementation",
            f"{canonical} benchmark comparison latency accuracy",
            f"{canonical} commercial tools and frameworks",
            f"{canonical} limitations failure modes deployment",
            f"{canonical} technical specifications evaluation",
        ]

        academic_queries = [
            self._clean_academic_query(f"{core_phrase} neural architecture"),
            self._clean_academic_query(f"{core_phrase} transformer model"),
            self._clean_academic_query(f"{core_phrase} optimization benchmark"),
            self._clean_academic_query(f"{core_phrase} empirical evaluation"),
            self._clean_academic_query(f"{core_phrase} survey review"),
        ]

        return {
            "canonical_topic": canonical,
            "domain_taxonomy": ["Computer Science", "Artificial Intelligence", "System Design"],
            "core_challenges": ["Algorithmic efficiency", "Hardware/software integration", "Generalization"],
            "web_queries": web_queries,
            "academic_queries": [q for q in academic_queries if q],
        }
