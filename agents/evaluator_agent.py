"""EvaluatorAgent: assesses feasibility, complexity, risks, and mitigations for proposed features."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard, Evaluation
from message import MessageBus, MessageType
from sources.jev_client import JevClient, decide_feasibility_sync

logger = logging.getLogger(__name__)


class EvaluatorAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 5,
        llm_client: Optional[Any] = None,
        jev_client: Optional[JevClient] = None,
    ) -> None:
        super().__init__(
            name="EvaluatorAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )
        self.jev = jev_client or JevClient()

    async def _run(self) -> List[Evaluation]:
        if not self.blackboard.proposed_features:
            logger.info("No proposed features to evaluate.")
            return []

        features_json = [
            {
                "feature_id": f.feature_id,
                "title": f.title,
                "description": f.description,
                "architecture_notes": f.architecture_notes,
            }
            for f in self.blackboard.proposed_features
        ]

        prompt = f"""You are a technical risk and engineering feasibility evaluator.
Evaluate the following proposed features for {self.blackboard.topic}:

FEATURES TO EVALUATE:
{features_json}

For each feature, provide:
1. feature_id: exact matching ID
2. feasibility_score: integer from 1 (nearly impossible) to 5 (readily achievable with standard tooling)
3. complexity_score: integer from 1 (trivial) to 5 (extreme engineering effort / multi-month research)
4. risk_level: "low", "medium", or "high"
5. risks: list of 2-3 specific technical or execution risks
6. mitigations: list of 2-3 concrete mitigation strategies
7. overall_assessment: 1-2 sentence engineering verdict

Return ONLY a JSON array of objects matching these keys.
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "claude-sonnet-5"),
                temperature=self.config.get("temperature", 0.2),
            )
            data = self.parse_json_response(raw_text)
            evaluations: List[Evaluation] = []
            evaluated_ids = set()
            for item in data:
                if isinstance(item, dict) and "feature_id" in item:
                    fid = str(item.get("feature_id", "")).strip()
                    evaluated_ids.add(fid)
                    risks = item.get("risks", [])
                    mitigations = item.get("mitigations", [])
                    overall_assessment = str(item.get("overall_assessment", "")).strip()

                    # Discrete decisions: If TYPESAFE_API_KEY is configured, Jev acts as primary discrete decision maker
                    if self.jev.api_key:
                        f_match = next((f for f in self.blackboard.proposed_features if f.feature_id == fid), None)
                        f_title = f_match.title if f_match else fid
                        f_desc = f_match.description if f_match else ""
                        f_arch = f_match.architecture_notes if f_match else ""
                        f_ctx = f"Feature: {f_title}\nDescription: {f_desc}\nArchitecture: {f_arch}\nRisks: {risks}\nMitigations: {mitigations}"

                        feas_dec = decide_feasibility_sync(
                            context=f_ctx,
                            min_score=1,
                            max_score=5,
                            prompt="Score implementation feasibility from 1 to 5.",
                            client=self.jev,
                        )
                        feasibility_score = feas_dec.value

                        comp_dec = decide_feasibility_sync(
                            context=f"Complexity assessment for: {f_ctx}",
                            min_score=1,
                            max_score=5,
                            prompt="Score engineering complexity from 1 to 5.",
                            client=self.jev,
                        )
                        complexity_score = comp_dec.value

                        risk_dec = self.jev.choice_sync(
                            context=f"Evaluate risk level given feasibility {feasibility_score}/5 and complexity {complexity_score}/5: {f_ctx}",
                            options=["low", "medium", "high"],
                            default=str(item.get("risk_level", "medium")).lower().strip() if str(item.get("risk_level", "medium")).lower().strip() in {"low", "medium", "high"} else "medium",
                        )
                        risk_level = risk_dec.value
                    else:
                        feasibility_score = int(item.get("feasibility_score", 3))
                        complexity_score = int(item.get("complexity_score", 3))
                        raw_risk = str(item.get("risk_level", "medium")).lower().strip()
                        if raw_risk not in {"low", "medium", "high"}:
                            risk_dec = self.jev.choice_sync(
                                context=f"Feature {fid} assessment: {overall_assessment}",
                                options=["low", "medium", "high"],
                                default="medium",
                            )
                            raw_risk = risk_dec.value
                        risk_level = raw_risk

                    ev = Evaluation(
                        feature_id=fid,
                        feasibility_score=feasibility_score,
                        complexity_score=complexity_score,
                        risk_level=risk_level,
                        risks=risks,
                        mitigations=mitigations,
                        overall_assessment=overall_assessment,
                    )
                    self.blackboard.add_evaluation(ev)
                    evaluations.append(ev)

            # Evaluate any missing features with Jev deterministic decision layer
            for f in self.blackboard.proposed_features:
                if f.feature_id not in evaluated_ids:
                    ev = self._deterministic_evaluate(f)
                    self.blackboard.add_evaluation(ev)
                    evaluations.append(ev)

            provider = "typesafe_jev_primary" if self.jev.api_key else "llm"
            self.send_message(
                recipient="*",
                msg_type=MessageType.EVALUATION_COMPLETE,
                payload={"count": len(evaluations), "provider": provider},
            )
            return evaluations
        except Exception as exc:
            logger.warning("LLM feature evaluation failed, falling back to Jev deterministic ladder: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            fallback_evals: List[Evaluation] = []
            for f in self.blackboard.proposed_features:
                ev = self._deterministic_evaluate(f)
                self.blackboard.add_evaluation(ev)
                fallback_evals.append(ev)

            self.send_message(
                recipient="*",
                msg_type=MessageType.EVALUATION_COMPLETE,
                payload={"count": len(fallback_evals), "provider": "jev_deterministic_fallback"},
            )
            return fallback_evals

    def _deterministic_evaluate(self, feature: Any) -> Evaluation:
        """Deterministic evaluation of a feature using JevClient."""
        f_ctx = f"Feature: {feature.title}\nDescription: {feature.description}\nArchitecture: {feature.architecture_notes}"
        feas_score = decide_feasibility_sync(
            context=f_ctx,
            min_score=1,
            max_score=5,
            prompt="Score implementation feasibility from 1 to 5.",
            client=self.jev,
        )
        comp_score = decide_feasibility_sync(
            context=f"Complexity assessment for: {f_ctx}",
            min_score=1,
            max_score=5,
            prompt="Score engineering complexity from 1 to 5.",
            client=self.jev,
        )
        risk_decision = self.jev.choice_sync(
            context=f"Evaluate risk level given feasibility {feas_score.value}/5 and complexity {comp_score.value}/5: {f_ctx}",
            options=["low", "medium", "high"],
            default="medium",
        )
        return Evaluation(
            feature_id=feature.feature_id,
            feasibility_score=feas_score.value,
            complexity_score=comp_score.value,
            risk_level=risk_decision.value,
            risks=[f"Potential complexity bottleneck in {feature.title}", "Integration dependency risk"],
            mitigations=["Adopt modular abstraction layer", "Perform benchmark stress testing"],
            overall_assessment=f"Deterministic evaluation via Jev ({feas_score.provider}): Feasibility {feas_score.value}/5, Complexity {comp_score.value}/5, Risk {risk_decision.value} (conf {feas_score.confidence:.2f}).",
        )
