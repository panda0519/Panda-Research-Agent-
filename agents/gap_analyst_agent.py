"""GapAnalystAgent: identifies technical, market, usability, and architectural gaps with academic evidence."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard, Gap
from message import MessageBus, MessageType
from sources.crossref_client import CrossrefClient, CrossrefWork
from sources.jev_client import JevClient, decide_gap_sync
from sources.openalex_client import OpenAlexClient, OpenAlexWork

logger = logging.getLogger(__name__)


class GapAnalystAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 3,
        llm_client: Optional[Any] = None,
        openalex_client: Optional[OpenAlexClient] = None,
        crossref_client: Optional[CrossrefClient] = None,
        jev_client: Optional[JevClient] = None,
    ) -> None:
        super().__init__(
            name="GapAnalystAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.openalex = openalex_client or OpenAlexClient()
        self.crossref = crossref_client or CrossrefClient()
        self.jev = jev_client or JevClient()

    async def _run(self) -> List[Gap]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        solutions_summary = "\n".join(
            [f"- {s.name} ({s.category}): {s.description}. Limitations: {', '.join(s.limitations)}" for s in self.blackboard.existing_solutions]
        )
        prior_context = "\n".join(self.blackboard.prior_context_notes[:3])

        # Broader Academic Gap Discovery Ladder: OpenAlex -> Crossref -> Baseline
        academic_gap_lines: List[str] = []
        try:
            # 1. Primary: OpenAlex for limitations / challenges
            oa_works = await self.openalex.search_works(f"{topic} limitations challenges bottlenecks benchmarks", limit=3)
            if oa_works:
                self.blackboard.metadata["gap_analyst_academic_search"] = "openalex"
                for w in oa_works:
                    abs_snip = f" - Abstract: {w.abstract[:180]}..." if w.abstract else ""
                    academic_gap_lines.append(f"- [OpenAlex] {w.title} ({w.publication_year or 'n.d.'}){abs_snip}")
            else:
                # 2. Backup: Crossref
                cr_works = await self.crossref.search_works(f"{topic} challenges limitations", limit=3)
                if cr_works:
                    self.blackboard.metadata["gap_analyst_academic_search"] = "crossref"
                    for w in cr_works:
                        abs_snip = f" - Abstract: {w.abstract[:180]}..." if w.abstract else ""
                        academic_gap_lines.append(f"- [Crossref] {w.title} ({w.year or 'n.d.'}){abs_snip}")
                else:
                    self.blackboard.metadata["gap_analyst_academic_search"] = "baseline"
        except Exception as disc_exc:
            logger.debug("GapAnalystAgent academic gap discovery fallback: %s", disc_exc)
            self.blackboard.metadata["gap_analyst_academic_search"] = "baseline"

        academic_context = "\n".join(academic_gap_lines)

        prompt = f"""You are a Principal AI Systems Architect and Technical Gap Analyst.
Analyze the current solution landscape and literature for {topic} in the context of: {context}.

EXISTING SOLUTIONS & LIMITATIONS:
{solutions_summary or 'None documented'}

ACADEMIC LITERATURE EVIDENCE & BOTTLENECKS:
{academic_context or 'None documented'}

PRIOR RUN MEMORY / CONTEXT:
{prior_context or 'None'}

Identify 3 to 5 critical gaps in the existing ecosystem. Focus on:
- Technical bottlenecks (latency, memory footprint, accuracy under edge conditions)
- Architectural limitations (tight coupling, closed ecosystems, lack of streaming)
- Usability or deployment barriers (complex pipelines, mobile/edge deployment hurdles)

For each gap, provide:
1. gap_id: e.g. "GAP-01", "GAP-02"
2. category: "technical", "market", "usability", or "architectural"
3. title: concise title
4. description: detailed explanation of the missing capability or bottleneck
5. evidence: list of strings (citing solution limitations or paper observations)
6. severity: "low", "medium", "high", or "critical"

Return ONLY a JSON array of objects.
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "claude-sonnet-5"),
                temperature=self.config.get("temperature", 0.4),
            )
            data = self.parse_json_response(raw_text)
            gaps: List[Gap] = []
            for item in data:
                if isinstance(item, dict) and "title" in item:
                    title = str(item.get("title", "")).strip()
                    desc = str(item.get("description", "")).strip()
                    ev_list = item.get("evidence", [])

                    # Discrete decisions: If TYPESAFE_API_KEY is configured, Jev acts as primary discrete decision maker
                    if self.jev.api_key:
                        sev_dec = decide_gap_sync(
                            context=f"Topic: {topic}\nGap title: {title}\nDescription: {desc}\nEvidence: {ev_list}",
                            options=["low", "medium", "high", "critical"],
                            client=self.jev,
                        )
                        raw_sev = sev_dec.value

                        cat_dec = self.jev.choice_sync(
                            context=f"Topic: {topic}\nGap title: {title}\nDescription: {desc}",
                            options=["technical", "market", "usability", "architectural"],
                            default=str(item.get("category", "technical")).lower().strip() if str(item.get("category", "technical")).lower().strip() in {"technical", "market", "usability", "architectural"} else "technical",
                        )
                        raw_cat = cat_dec.value
                    else:
                        raw_sev = str(item.get("severity", "medium")).lower().strip()
                        if raw_sev not in {"low", "medium", "high", "critical"}:
                            sev_dec = decide_gap_sync(
                                context=f"Gap title: {title}\nDescription: {desc}",
                                options=["low", "medium", "high", "critical"],
                                client=self.jev,
                            )
                            raw_sev = sev_dec.value

                        raw_cat = str(item.get("category", "technical")).lower().strip()
                        if raw_cat not in {"technical", "market", "usability", "architectural"}:
                            cat_dec = self.jev.choice_sync(
                                context=f"Gap title: {title}\nDescription: {desc}",
                                options=["technical", "market", "usability", "architectural"],
                                default="technical",
                            )
                            raw_cat = cat_dec.value

                    gap = Gap(
                        gap_id=str(item.get("gap_id", f"GAP-{len(gaps)+1:02d}")).strip(),
                        category=raw_cat,
                        title=title,
                        description=desc,
                        evidence=ev_list,
                        severity=raw_sev,
                    )
                    self.blackboard.add_gap(gap)
                    gaps.append(gap)

            if not gaps:
                gaps = self._fallback_gaps(topic, solutions_summary, academic_gap_lines)

            provider = "typesafe_jev_primary" if self.jev.api_key else "llm"
            self.send_message(
                recipient="*",
                msg_type=MessageType.GAPS_IDENTIFIED,
                payload={"count": len(gaps), "gaps": [g.title for g in gaps], "provider": provider},
            )
            return gaps
        except Exception as exc:
            logger.warning("GapAnalystAgent LLM generation failed, using Jev deterministic fallback: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            fallback_gaps = self._fallback_gaps(topic, solutions_summary, academic_gap_lines)
            self.send_message(
                recipient="*",
                msg_type=MessageType.GAPS_IDENTIFIED,
                payload={"count": len(fallback_gaps), "gaps": [g.title for g in fallback_gaps], "provider": "jev_fallback"},
            )
            return fallback_gaps

    def _fallback_gaps(self, topic: str, solutions_summary: str, academic_gap_lines: List[str]) -> List[Gap]:
        """Constructs deterministic fallback gaps dynamically grounded in the topic, solutions, and academic findings."""
        gaps: List[Gap] = []
        candidates: List[tuple[str, str, List[str], str]] = []

        # 1. Grounded in existing solutions & their stated limitations
        for sol in self.blackboard.existing_solutions:
            if sol.limitations:
                lims_str = "; ".join(sol.limitations[:2])
                c_title = f"Bottlenecks in {sol.name}"
                c_desc = f"Identified limitations in {sol.name}: {lims_str}. This restricts performance and adoption in {topic} workflows."
                c_ev = [f"{sol.name} limitation: {lim}" for lim in sol.limitations[:2]]
                candidates.append((c_title, c_desc, c_ev, "technical"))
            else:
                c_title = f"Scope Limitations in {sol.name}"
                c_desc = f"Current implementation of {sol.name} ({sol.category}) does not fully address complex {topic} requirements."
                c_ev = [f"{sol.name}: {sol.description[:120]}"] if sol.description else []
                candidates.append((c_title, c_desc, c_ev, "architectural"))

        # 2. Grounded in academic literature findings
        for acad_line in academic_gap_lines[:2]:
            clean_acad = acad_line.lstrip("- ").strip()
            c_title = f"Research Bottleneck in {topic.capitalize()}"
            c_desc = f"Academic literature highlights unresolved challenges in {topic}: {clean_acad[:180]}."
            candidates.append((c_title, c_desc, [clean_acad[:120]], "technical"))

        # 3. Topic-grounded fallback archetypes if fewer than 3 candidates
        topic_clean = topic.strip() or "System Architecture"
        archetypes = [
            (
                f"Scalability and Latency Bottlenecks in {topic_clean}",
                f"High computational complexity and resource overhead when executing {topic_clean} under production or constrained environments.",
                [solutions_summary[:100]] if solutions_summary else [f"Identified during landscape analysis of {topic_clean}"],
                "technical",
            ),
            (
                f"Architectural Fragmentation and Interoperability in {topic_clean}",
                f"Lack of unified interfaces and standard data protocols across heterogeneous implementations in {topic_clean}.",
                [solutions_summary[:100]] if solutions_summary else [f"Identified during architectural review of {topic_clean}"],
                "architectural",
            ),
            (
                f"Edge-Case Robustness and Benchmark Standardization in {topic_clean}",
                f"Performance degradation and lack of standardized evaluation benchmarks across real-world edge cases in {topic_clean}.",
                [academic_gap_lines[0][:100]] if academic_gap_lines else [f"Identified during validation analysis of {topic_clean}"],
                "usability",
            ),
        ]

        for arch_title, arch_desc, arch_ev, arch_cat in archetypes:
            if len(candidates) < 3:
                candidates.append((arch_title, arch_desc, arch_ev, arch_cat))

        # Use Jev to classify severity and category for each candidate
        for idx, (title, desc, ev_list, default_cat) in enumerate(candidates[:5], 1):
            sev_dec = decide_gap_sync(
                context=f"Topic: {topic}\nGap: {title} - {desc}\nEvidence: {' '.join(ev_list)}",
                options=["low", "medium", "high", "critical"],
                client=self.jev,
            )
            cat_dec = self.jev.choice_sync(
                context=f"Topic: {topic}\nGap: {title} - {desc}",
                options=["technical", "market", "usability", "architectural"],
                default=default_cat,
            )
            gap = Gap(
                gap_id=f"GAP-{idx:02d}",
                category=cat_dec.value,
                title=title,
                description=desc,
                evidence=ev_list,
                severity=sev_dec.value,
            )
            self.blackboard.add_gap(gap)
            gaps.append(gap)
        return gaps
