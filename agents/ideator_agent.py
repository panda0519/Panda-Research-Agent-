"""IdeatorAgent: designs novel architectures and features targeting identified gaps."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard, Feature
from message import MessageBus, MessageType

logger = logging.getLogger(__name__)


class IdeatorAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 4,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name="IdeatorAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )

    async def _run(self) -> List[Feature]:
        topic = self.blackboard.topic
        context = self.blackboard.project_context

        gaps_summary = "\n".join([f"- [{g.gap_id}] {g.title} ({g.severity}): {g.description}" for g in self.blackboard.gaps])

        prompt = f"""You are a visionary AI systems architect and product ideator.
Design 3 to 5 high-impact, novel features or architectural mechanisms for:
Topic: {topic}
Project Context: {context}

TARGET GAPS TO SOLVE:
{gaps_summary or 'None documented'}

For each proposed feature or mechanism:
1. feature_id: e.g. "FEAT-01", "FEAT-02"
2. title: descriptive feature name
3. description: clear explanation of what the feature does
4. target_gap_ids: list of gap IDs (e.g. ["GAP-01", "GAP-02"]) that this feature addresses
5. architecture_notes: concrete implementation details, algorithm design, data flow
6. novelty_rationale: why this approach is distinct and superior to existing solutions

Return ONLY a JSON array of objects.
"""
        try:
            raw_text = self.llm.generate(
                prompt=prompt,
                model=self.config.get("model", "claude-sonnet-5"),
                temperature=self.config.get("temperature", 0.7),
            )
            data = self.parse_json_response(raw_text)
            features: List[Feature] = []
            for item in data:
                if isinstance(item, dict) and "title" in item:
                    feat = Feature(
                        feature_id=str(item.get("feature_id", f"FEAT-{len(features)+1:02d}")).strip(),
                        title=str(item.get("title", "")).strip(),
                        description=str(item.get("description", "")).strip(),
                        target_gap_ids=item.get("target_gap_ids", []),
                        architecture_notes=str(item.get("architecture_notes", "")).strip(),
                        novelty_rationale=str(item.get("novelty_rationale", "")).strip(),
                    )
                    self.blackboard.add_feature(feat)
                    features.append(feat)

            self.send_message(
                recipient="*",
                msg_type=MessageType.FEATURES_PROPOSED,
                payload={"count": len(features), "features": [f.title for f in features]},
            )
            return features
        except Exception as exc:
            logger.error("IdeatorAgent failed: %s", exc)
            self.blackboard.metadata.setdefault("phase_errors", {})[self.phase_name] = str(exc)
            return []
