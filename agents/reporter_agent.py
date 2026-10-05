"""ReporterAgent: synthesizes all Blackboard artifacts into a publication-grade markdown report."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from blackboard import Blackboard
from message import MessageBus, MessageType
from verification.pipeline import VerificationPipeline

logger = logging.getLogger(__name__)


class ReporterAgent(BaseAgent):
    def __init__(
        self,
        blackboard: Blackboard,
        bus: MessageBus,
        phase: int = 8,
        llm_client: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name="ReporterAgent",
            blackboard=blackboard,
            bus=bus,
            phase=phase,
            llm_client=llm_client,
        )

    async def _run(self) -> str:
        logger.info("ReporterAgent compiling final markdown report.")
        report = self.generate_report()
        self.blackboard.report_markdown = report

        self.send_message(
            recipient="*",
            msg_type=MessageType.REPORT_GENERATED,
            payload={"length": len(report), "preview": report[:200]},
        )
        return report

    def generate_report(self) -> str:
        bb = self.blackboard
        sections: List[str] = []

        canonical_topic = bb.metadata.get("canonical_topic", bb.topic)
        query_plan = bb.metadata.get("query_plan", {})
        taxonomy = query_plan.get("domain_taxonomy", [])
        challenges = query_plan.get("core_challenges", [])

        # Title & Metadata
        sections.append(f"# Deep Research Report: {canonical_topic}\n")
        sections.append(f"**Run ID:** `{bb.run_id}`  \n**Project Context:** {bb.project_context or 'General Technical Synthesis'}  ")
        if taxonomy:
            sections.append(f"**Domain Taxonomy:** {', '.join(taxonomy)}  ")
        sections.append("")

        # 1. Executive Summary & Research Metrics Dashboard
        sections.append("## 1. Executive Summary & Research Metrics Dashboard")
        summary_points = [
            f"- **Sources & Deep Literature:** {len(bb.sources)} verified multi-engine web sources, {len(bb.paper_notes)} academic papers ingested.",
            f"- **Ecosystem State:** Evaluated {len(bb.existing_solutions)} existing solutions and identified {len(bb.gaps)} core technical/architectural gaps.",
            f"- **Proposed Innovations:** {len(bb.proposed_features)} novel technical features designed with concrete architectural specifications.",
            f"- **Technology Stack:** {len(bb.tech_stack)} architecture layers evaluated with live repository health checks.",
            f"- **Verification Integrity:** {len(bb.claim_verifications)} claims audited across 3 validation layers.",
        ]
        sections.append("\n".join(summary_points) + "\n")

        if challenges:
            sections.append("### Core Technical Challenges Under Investigation")
            for c in challenges:
                sections.append(f"- **Hurdle:** {c}")
            sections.append("")

        # 2. Academic Literature Review
        if bb.paper_notes:
            sections.append("## 2. Academic Literature Review")
            for p in bb.paper_notes:
                authors = ", ".join(p.authors[:3]) + (" et al." if len(p.authors) > 3 else "")
                year_str = f" ({p.year})" if p.year else ""
                venue_str = f" *[{p.venue}]*" if p.venue else ""
                sections.append(f"### {p.title}{year_str}{venue_str}")
                oa_badge = f" | **Open Access:** [Full Text PDF]({p.full_text_url}) (`{p.oa_source}`)" if (p.is_open_access and p.full_text_url) else ""
                sections.append(f"**Authors:** {authors or 'N/A'} | **Source:** `{p.source_api}` | **Link:** [{p.url}]({p.url}){oa_badge}")
                if p.takeaways:
                    sections.append(f"**Key Takeaway & Methodology:** {p.takeaways}\n")
                elif p.abstract:
                    sections.append(f"**Abstract:** {p.abstract[:400]}...\n")

        # 3. State-of-the-Art & Landscape
        if bb.existing_solutions:
            sections.append("## 3. State-of-the-Art & Existing Solutions")
            for s in bb.existing_solutions:
                sections.append(f"### {s.name} (`{s.category}`)")
                sections.append(f"{s.description}\n")
                if s.strengths:
                    sections.append(f"- **Strengths:** {', '.join(s.strengths)}")
                if s.limitations:
                    sections.append(f"- **Limitations:** {', '.join(s.limitations)}")
                if s.sources:
                    sections.append(f"- **Sources:** {', '.join([f'[{u}]({u})' for u in s.sources])}")
                sections.append("")

        # 4. Gap Analysis
        if bb.gaps:
            sections.append("## 4. Technical & Architectural Gaps")
            for g in bb.gaps:
                sections.append(f"### [{g.gap_id}] {g.title} (Severity: `{g.severity.upper()}` | Category: `{g.category}`)")
                sections.append(f"{g.description}\n")
                if g.evidence:
                    sections.append(f"**Evidence / Precedent:** {', '.join(g.evidence)}\n")


        # 5. Proposed Features & Novel Architecture
        if bb.proposed_features:
            sections.append("## 5. Proposed Features & Architecture")
            for f in bb.proposed_features:
                sections.append(f"### [{f.feature_id}] {f.title}")
                sections.append(f"{f.description}\n")
                if f.target_gap_ids:
                    sections.append(f"- **Addresses Gaps:** {', '.join([f'`{gid}`' for gid in f.target_gap_ids])}")
                if f.novelty_rationale:
                    sections.append(f"- **Novelty Rationale:** {f.novelty_rationale}")
                if f.architecture_notes:
                    sections.append(f"- **Architecture Details:** {f.architecture_notes}")
                sections.append("")

        # 6. Technology Stack Recommendations
        if bb.tech_stack:
            sections.append("## 6. Recommended Technology Stack")
            for ts in bb.tech_stack:
                sections.append(f"### Layer: {ts.layer.replace('_', ' ').title()}")
                sections.append(f"- **Selected Technology:** `{ts.selected_tech}`")
                if ts.repo_url:
                    sections.append(f"- **Repository:** [{ts.repo_url}]({ts.repo_url})")
                if ts.health_notes:
                    sections.append(f"- **GitHub Health:** {ts.health_notes}")
                if ts.alternatives_considered:
                    sections.append(f"- **Alternatives Considered:** {', '.join(ts.alternatives_considered)}")
                if ts.rationale:
                    sections.append(f"- **Rationale:** {ts.rationale}")
                sections.append("")

        # 7. Engineering Evaluations & Risk Matrix
        if bb.evaluations:
            sections.append("## 7. Engineering Evaluations & Risk Analysis")
            sections.append("| Feature ID | Feasibility (1-5) | Complexity (1-5) | Risk Level | Assessment |")
            sections.append("|------------|-------------------|------------------|------------|------------|")
            for e in bb.evaluations:
                sections.append(f"| `{e.feature_id}` | {e.feasibility_score}/5 | {e.complexity_score}/5 | `{e.risk_level.upper()}` | {e.overall_assessment} |")
            sections.append("")

        # 8. Verification Pipeline Summary & Badges
        sections.append("## 8. 3-Layer Verification Summary")
        if bb.claim_verifications:
            sections.append("### Claim Verification Audit")
            for cv in bb.claim_verifications:
                badge = VerificationPipeline.format_badge(cv.status, single_engine=cv.single_engine)
                sections.append(f"- {badge} **[{cv.source_agent}]** {cv.claim_text}")
                if cv.rationale:
                    sections.append(f"  - *Rationale:* {cv.rationale}")
            sections.append("")

        if bb.consistency_issues:
            sections.append("### Consistency Audit Notes")
            for issue in bb.consistency_issues:
                sections.append(f"- ⚠ {issue}")
            sections.append("")

        # 8.3 External Verification Sources & Fallback Ladder Matrix
        sections.append("### External Verification Sources & Provenance Matrix")
        sections.append("| Specialization | Fallback Ladder | Status in Run |")
        sections.append("|----------------|-----------------|---------------|")

        # 1. Repo Health
        gh_mode = bb.metadata.get("github_access_mode")
        if gh_mode == "authenticated":
            gh_status = "Primary (GitHub Authenticated)"
        elif gh_mode == "unauthenticated":
            gh_status = "Backup (GitHub Unauthenticated)"
        else:
            has_gh = any(ts.repo_url and "github.com" in ts.repo_url for ts in bb.tech_stack)
            gh_status = "Active (GitHub REST)" if has_gh else "Baseline (Model Knowledge)"
        sections.append(f"| Repo Health (TechStack) | GitHub REST API → Baseline LLM | `{gh_status}` |")

        # 2. Academic Full Text
        oa_count = sum(1 for p in bb.paper_notes if p.is_open_access and p.full_text_url)
        oa_mode = bb.metadata.get("oa_access_mode")
        if oa_mode == "unpaywall":
            oa_status = f"Primary (Unpaywall OA, {oa_count} resolved)"
        elif oa_mode == "core":
            oa_status = f"Backup (CORE OA, {oa_count} resolved)"
        elif oa_mode == "arxiv":
            oa_status = f"Active (arXiv Native, {oa_count} resolved)"
        elif oa_count > 0:
            oa_status = f"Active ({oa_count} Open Access resolved)"
        else:
            oa_status = "Baseline (Abstract Summaries)"
        sections.append(f"| Academic Full Text (PaperReader) | Unpaywall → CORE → Baseline Abstracts | `{oa_status}` |")

        # 3. Second-Model Claim Check
        model_mode = bb.metadata.get("second_model_used")
        if model_mode == "Groq (Llama 3.3 70B)":
            l2_status = "Primary (Groq Llama 3.3 70B)"
        elif model_mode == "Gemini (gemini-2.5-flash)":
            l2_status = "Backup (Google Gemini)"
        elif bb.claim_verifications:
            l2_status = "Baseline (Single-Model Haiku)"
        else:
            l2_status = "Baseline (No Claims Checked)"
        sections.append(f"| Second-Model Claim Check (Layer 2) | Groq (Llama 3.3 70B) → Gemini → Baseline | `{l2_status}` |")

        # 4. Broader Academic Discovery
        surv_disc = bb.metadata.get("surveyor_academic_search")
        gap_disc = bb.metadata.get("gap_analyst_academic_search")
        if surv_disc == "openalex" or gap_disc == "openalex":
            acad_status = "Primary (OpenAlex Citations & Concepts)"
        elif surv_disc == "crossref" or gap_disc == "crossref":
            acad_status = "Backup (Crossref DOI & Citations)"
        else:
            acad_status = "Baseline (Web & Literature Search)"
        sections.append(f"| Broader Academic Discovery (Surveyor / GapAnalyst) | OpenAlex → Crossref → Baseline Search | `{acad_status}` |")

        # 5. Computational Claim Check
        comp_mode = bb.metadata.get("computational_checker_used")
        if comp_mode == "Wolfram Alpha":
            comp_status = "Primary (Wolfram Alpha API)"
        elif comp_mode == "Deterministic AST (Local)":
            comp_status = "Backup (Deterministic Local AST)"
        else:
            has_comp = any("Deterministic Compute" in (cv.rationale or "") or "Wolfram Alpha" in (cv.rationale or "") for cv in bb.claim_verifications)
            comp_status = "Active (Deterministic AST / Wolfram)" if has_comp else "Baseline (Textual LLM Evaluation)"
        sections.append(f"| Computational Claim Check (Layer 2/3) | Wolfram Alpha → Deterministic AST → Baseline | `{comp_status}` |")
        sections.append("")

        # 9. Rubric Audit Scorecard
        if bb.rubric_scores:
            sections.append("## 9. Rubric Self-Audit Scorecard")
            total_weighted_score = 0.0
            total_weight = 0.0
            for r in bb.rubric_scores:
                total_weighted_score += r.score * r.weight
                total_weight += r.weight
                sections.append(f"### Criterion: {r.criterion} (Score: `{r.score:.1f}/10.0` | Weight: `{r.weight}`)")
                sections.append(f"- **Strengths:** {r.strengths}")
                sections.append(f"- **Weaknesses:** {r.weaknesses}")
                if r.evidence_citations:
                    sections.append(f"- **Evidence Cited:** {', '.join(r.evidence_citations)}")
                sections.append("")

            if total_weight > 0:
                final_score = total_weighted_score / total_weight
                sections.append(f"**Overall Weighted Score:** `{final_score:.2f} / 10.0`\n")

        # 10. References & Source Provenance
        if bb.sources:
            sections.append("## 10. Verified Source Index")
            for s in bb.sources:
                engines_badge = f"`[{', '.join(s.engines)}]`"
                trust_badge = f"`Trust: {s.trust_score:.2f}`"
                sections.append(f"- [{s.title}]({s.url}) — {engines_badge} {trust_badge}")
            sections.append("")

        return "\n".join(sections)
