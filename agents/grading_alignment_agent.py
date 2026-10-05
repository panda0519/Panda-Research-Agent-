"""GradingAlignmentAgent: parses arbitrary rubrics and self-audits Blackboard evidence."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from agents.base import BaseAgent
from blackboard import Blackboard, RubricScoreItem
from message import MessageBus, MessageType
from sources.jev_client import JevClient, decide_feasibility_sync, decide_verdict_sync

logger = logging.getLogger(__name__)


class GradingAlignmentAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 7,
        llm_client: Optional[Any] = None,
        jev_client: Optional[JevClient] = None,
    ) -> None:
        super().__init__(
            name="GradingAlignmentAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.jev = jev_client or JevClient()

    async def _run(self, rubric_input: Optional[str] = None, rubric_path: Optional[str] = None) -> List[RubricScoreItem]:
        content = ""
        if rubric_path:
            p = Path(rubric_path)
            if p.exists():
                content = p.read_text(encoding="utf-8")
        elif rubric_input:
            content = rubric_input

        if not content:
            logger.info("No rubric supplied; skipping GradingAlignmentAgent.")
            return []

        criteria = self.parse_rubric(content)
        if not criteria:
            logger.warning("Could not parse criteria from rubric.")
            return []

        scores = await self.audit_against_criteria(criteria)
        for s in scores:
            self.blackboard.rubric_scores.append(s)

        self.send_message(
            recipient="*",
            msg_type=MessageType.RUBRIC_AUDIT_COMPLETE,
            payload={"criteria_evaluated": len(scores)},
        )
        return scores

    def parse_rubric(self, content: str) -> List[Dict[str, Any]]:
        clean = content.strip()

        # 1. Try JSON / YAML structured format
        try:
            data = yaml.safe_load(clean)
            if isinstance(data, dict):
                items = data.get("criteria") or data.get("categories") or data.get("rubric") or []
                if isinstance(items, list) and items:
                    parsed = []
                    for it in items:
                        if isinstance(it, dict):
                            parsed.append(
                                {
                                    "criterion": it.get("criterion") or it.get("name") or "Unnamed Criterion",
                                    "weight": float(it.get("weight", 1.0)),
                                    "description": it.get("description", ""),
                                }
                            )
                        elif isinstance(it, str):
                            parsed.append({"criterion": it, "weight": 1.0, "description": ""})
                    if parsed:
                        return parsed
            elif isinstance(data, list):
                parsed = []
                for it in data:
                    if isinstance(it, dict):
                        parsed.append(
                            {
                                "criterion": it.get("criterion") or it.get("name") or "Unnamed",
                                "weight": float(it.get("weight", 1.0)),
                                "description": it.get("description", ""),
                            }
                        )
                if parsed:
                    return parsed
        except Exception:
            pass

        # 2. Try Markdown checklist pattern: "- [ ] Criterion text (weight: X%)"
        checklist_pattern = r"[-*]\s*\[[ xX]?\]\s*([^(\n\r]+)(?:\((?:weight:\s*)?([0-9.]+)(?:%|pts)?\))?"
        matches = re.findall(checklist_pattern, clean)
        if matches and len(matches) >= 2:
            parsed = []
            for criterion_text, weight_str in matches:
                criterion_clean = criterion_text.strip()
                weight = float(weight_str.strip()) if weight_str.strip() else 1.0
                parsed.append({"criterion": criterion_clean, "weight": weight, "description": criterion_clean})
            return parsed

        # 3. Fallback: LLM extraction for free-text rubrics
        return self._extract_criteria_with_llm(clean)

    def _extract_criteria_with_llm(self, text: str) -> List[Dict[str, Any]]:
        prompt = f"""Extract all evaluation criteria from the following text into a JSON list:
TEXT:
{text}

Return ONLY a JSON array:
[{{"criterion": "Name", "weight": 1.0, "description": "Details"}}]
"""
        try:
            raw = self.llm.generate(prompt=prompt, temperature=0.0)
            data = self.parse_json_response(raw)
            if isinstance(data, list):
                return [
                    {
                        "criterion": str(d.get("criterion", "Unnamed")),
                        "weight": float(d.get("weight", 1.0)),
                        "description": str(d.get("description", "")),
                    }
                    for d in data
                    if isinstance(d, dict)
                ]
        except Exception as e:
            logger.warning("LLM rubric extraction failed: %s", e)
        return [{"criterion": "Overall Quality", "weight": 1.0, "description": text[:200]}]

    async def audit_against_criteria(self, criteria: List[Dict[str, Any]]) -> List[RubricScoreItem]:
        evidence_summary = (
            f"Sources count: {len(self.blackboard.sources)}\n"
            f"Academic papers count: {len(self.blackboard.paper_notes)}\n"
            f"Gaps identified: {len(self.blackboard.gaps)}\n"
            f"Proposed features: {len(self.blackboard.proposed_features)}\n"
            f"Tech stack layers: {len(self.blackboard.tech_stack)}\n"
            f"Verifications: {len(self.blackboard.claim_verifications)}\n"
            f"Consistency issues: {len(self.blackboard.consistency_issues)}\n"
        )

        gaps_list = [g.title for g in self.blackboard.gaps]
        features_list = [f.title for f in self.blackboard.proposed_features]
        evals_list = [f"{e.feature_id}: Feas={e.feasibility_score}/5, Complex={e.complexity_score}/5" for e in self.blackboard.evaluations]

        prompt = f"""You are a rigorous technical grader auditing a research agent run.
Score the research artifacts against each criterion based on actual evidence.

BLACKBOARD SUMMARY:
{evidence_summary}

GAPS:
{gaps_list}

FEATURES:
{features_list}

EVALUATIONS:
{evals_list}

CRITERIA:
{json.dumps(criteria, indent=2)}

For each criterion:
1. criterion: exact matching name
2. weight: float
3. score: score out of 10.0 (e.g. 8.5)
4. strengths: 1-2 sentences citing actual evidence
5. weaknesses: 1-2 sentences identifying areas for improvement
6. evidence_citations: list of specific gap IDs, feature IDs, or paper titles cited

Return ONLY a JSON array of objects.
"""
        try:
            raw = self.llm.generate(prompt=prompt, temperature=0.1)
            data = self.parse_json_response(raw)
            scores: List[RubricScoreItem] = []
            evaluated_criteria = set()
            for item in data:
                if isinstance(item, dict) and "criterion" in item:
                    crit_name = str(item.get("criterion", "")).strip()
                    evaluated_criteria.add(crit_name)
                    c_meta = next((c for c in criteria if c.get("criterion") == crit_name or c.get("name") == crit_name), {})
                    c_desc = c_meta.get("description", "")
                    strengths = str(item.get("strengths", "")).strip()
                    weaknesses = str(item.get("weaknesses", "")).strip()
                    ev_citations = item.get("evidence_citations", [])

                    # Discrete score decision: If TYPESAFE_API_KEY is configured, Jev acts as primary score decision maker
                    if self.jev.api_key:
                        jev_ctx = f"Criterion: {crit_name} ({c_desc})\nStrengths: {strengths}\nWeaknesses: {weaknesses}\nEvidence Summary:\n{evidence_summary}"
                        jev_score = decide_feasibility_sync(context=jev_ctx, min_score=1, max_score=10, client=self.jev)
                        crit_score = float(jev_score.value)
                    else:
                        crit_score = float(item.get("score", 7.0))

                    scores.append(
                        RubricScoreItem(
                            criterion=crit_name,
                            weight=float(item.get("weight", c_meta.get("weight", 1.0))),
                            score=crit_score,
                            strengths=strengths,
                            weaknesses=weaknesses,
                            evidence_citations=ev_citations,
                        )
                    )
            # Fill missing criteria with Jev deterministic decision layer
            for c in criteria:
                c_name = c.get("criterion", "Unnamed")
                if c_name not in evaluated_criteria:
                    jev_ctx = f"Criterion: {c_name} ({c.get('description', '')})\nEvidence Summary:\n{evidence_summary}"
                    jev_score = decide_feasibility_sync(context=jev_ctx, min_score=1, max_score=10, client=self.jev)
                    jev_verdict = decide_verdict_sync(context=jev_ctx, options=["MET", "PARTIALLY_MET", "NOT_MET"], client=self.jev)
                    scores.append(
                        RubricScoreItem(
                            criterion=c_name,
                            weight=float(c.get("weight", 1.0)),
                            score=float(jev_score.value),
                            strengths=f"Deterministic evaluation verdict: {jev_verdict.value}. {jev_verdict.reasoning}".strip(),
                            weaknesses=f"Calibrated via TypeSafe Jev ({jev_score.provider}) with confidence {jev_score.confidence:.2f}.",
                            evidence_citations=gaps_list[:2] + features_list[:2],
                        )
                    )
            return scores
        except Exception as exc:
            logger.warning("LLM rubric audit failed, falling back to Jev deterministic evaluation: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            fallback_scores: List[RubricScoreItem] = []
            for c in criteria:
                c_name = c.get("criterion", "Unnamed")
                jev_ctx = f"Criterion: {c_name} ({c.get('description', '')})\nEvidence Summary:\n{evidence_summary}"
                jev_score = decide_feasibility_sync(context=jev_ctx, min_score=1, max_score=10, client=self.jev)
                jev_verdict = decide_verdict_sync(context=jev_ctx, options=["MET", "PARTIALLY_MET", "NOT_MET"], client=self.jev)
                fallback_scores.append(
                    RubricScoreItem(
                        criterion=c_name,
                        weight=float(c.get("weight", 1.0)),
                        score=float(jev_score.value),
                        strengths=f"Deterministic evaluation verdict: {jev_verdict.value}. {jev_verdict.reasoning}".strip(),
                        weaknesses=f"Audit completed via Jev deterministic fallback ladder ({jev_score.provider}).",
                        evidence_citations=gaps_list[:2] + features_list[:2],
                    )
                )
            return fallback_scores
