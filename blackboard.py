"""Shared blackboard datastructure for all agents in a research run."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from live_trace.hooks import trace_blackboard_update


@dataclass
class Source:
    url: str
    title: str
    snippet: str
    engines: List[str] = field(default_factory=list)
    trust_score: float = 1.0
    domain: str = ""
    is_reachable: bool = True
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PaperNote:
    title: str
    authors: List[str]
    year: Optional[int]
    url: str
    source_api: str  # "arxiv" or "semantic_scholar"
    abstract: str
    takeaways: str = ""
    citations_count: Optional[int] = None
    venue: str = ""
    doi: Optional[str] = None
    full_text_url: Optional[str] = None
    is_open_access: bool = False
    oa_source: Optional[str] = None
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Solution:
    name: str
    category: str
    description: str
    strengths: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)


@dataclass
class Gap:
    gap_id: str
    category: str
    title: str
    description: str
    evidence: List[str] = field(default_factory=list)
    severity: str = "medium"


@dataclass
class Feature:
    feature_id: str
    title: str
    description: str
    target_gap_ids: List[str] = field(default_factory=list)
    architecture_notes: str = ""
    novelty_rationale: str = ""


@dataclass
class TechStackRecommendation:
    layer: str
    selected_tech: str
    alternatives_considered: List[str] = field(default_factory=list)
    rationale: str = ""
    repo_url: Optional[str] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    open_issues: Optional[int] = None
    license: Optional[str] = None
    is_archived: bool = False
    last_pushed_at: Optional[str] = None
    health_notes: Optional[str] = None


@dataclass
class Evaluation:
    feature_id: str
    feasibility_score: int
    complexity_score: int
    risk_level: str
    risks: List[str] = field(default_factory=list)
    mitigations: List[str] = field(default_factory=list)
    overall_assessment: str = ""



@dataclass
class Blackboard:
    run_id: str
    topic: str
    project_context: str = ""
    prior_context_notes: List[str] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    paper_notes: List[PaperNote] = field(default_factory=list)
    existing_solutions: List[Solution] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    proposed_features: List[Feature] = field(default_factory=list)
    tech_stack: List[TechStackRecommendation] = field(default_factory=list)
    evaluations: List[Evaluation] = field(default_factory=list)
    claim_verifications: List[ClaimVerification] = field(default_factory=list)
    consistency_issues: List[str] = field(default_factory=list)
    rubric_scores: List[RubricScoreItem] = field(default_factory=list)
    report_markdown: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_source(self, source: Source) -> None:
        self.sources.append(source)
        trace_blackboard_update("sources", count=len(self.sources), detail=source.title)

    def add_sources(self, sources: List[Source]) -> None:
        for s in sources:
            self.sources.append(s)
        trace_blackboard_update("sources", count=len(self.sources), detail=f"+{len(sources)} sources")

    def add_paper_note(self, note: PaperNote) -> None:
        self.paper_notes.append(note)
        trace_blackboard_update("paper_notes", count=len(self.paper_notes), detail=note.title)

    def add_solution(self, solution: Solution) -> None:
        self.existing_solutions.append(solution)
        trace_blackboard_update("existing_solutions", count=len(self.existing_solutions), detail=solution.name)

    def add_gap(self, gap: Gap) -> None:
        self.gaps.append(gap)
        trace_blackboard_update("gaps", count=len(self.gaps), detail=gap.title)

    def add_feature(self, feature: Feature) -> None:
        self.proposed_features.append(feature)
        trace_blackboard_update("proposed_features", count=len(self.proposed_features), detail=feature.title)

    def add_tech_stack_item(self, item: TechStackRecommendation) -> None:
        self.tech_stack.append(item)
        trace_blackboard_update("tech_stack", count=len(self.tech_stack), detail=f"{item.layer}: {item.selected_tech}")

    def add_evaluation(self, evaluation: Evaluation) -> None:
        self.evaluations.append(evaluation)
        trace_blackboard_update("evaluations", count=len(self.evaluations), detail=f"Feature {evaluation.feature_id}")

    def add_claim_verification(self, verification: ClaimVerification) -> None:
        self.claim_verifications.append(verification)
        trace_blackboard_update("claim_verifications", count=len(self.claim_verifications), detail=verification.status)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Blackboard:
        sources = [Source(**s) for s in data.get("sources", [])]
        paper_notes = [PaperNote(**p) for p in data.get("paper_notes", [])]
        solutions = [Solution(**sol) for sol in data.get("existing_solutions", [])]
        gaps = [Gap(**g) for g in data.get("gaps", [])]
        features = [Feature(**f) for f in data.get("proposed_features", [])]
        tech_stack = [TechStackRecommendation(**ts) for ts in data.get("tech_stack", [])]
        evaluations = [Evaluation(**e) for e in data.get("evaluations", [])]
        claim_verifications = [ClaimVerification(**cv) for cv in data.get("claim_verifications", [])]
        rubric_scores = [RubricScoreItem(**rs) for rs in data.get("rubric_scores", [])]

        return cls(
            run_id=data.get("run_id", ""),
            topic=data.get("topic", ""),
            project_context=data.get("project_context", ""),
            prior_context_notes=data.get("prior_context_notes", []),
            sources=sources,
            paper_notes=paper_notes,
            existing_solutions=solutions,
            gaps=gaps,
            proposed_features=features,
            tech_stack=tech_stack,
            evaluations=evaluations,
            claim_verifications=claim_verifications,
            consistency_issues=data.get("consistency_issues", []),
            rubric_scores=rubric_scores,
            report_markdown=data.get("report_markdown", ""),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Blackboard:
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class ClaimVerification:
    claim_text: str
    source_agent: str
    cited_urls: List[str] = field(default_factory=list)
    status: str = "NEEDS_HUMAN"
    single_engine: bool = False
    rationale: str = ""


@dataclass
class RubricScoreItem:
    criterion: str
    weight: float
    score: float
    strengths: str
    weaknesses: str
    evidence_citations: List[str] = field(default_factory=list)
