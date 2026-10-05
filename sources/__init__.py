"""Sources package for external academic, code repository, LLM, and computational verification clients."""
from sources.core_client import CoreClient, CorePaper, search_core
from sources.crossref_client import CrossrefClient, CrossrefWork, search_crossref
from sources.github_client import GitHubClient, GitHubRepoHealth, fetch_repo_health
from sources.groq_client import GroqClient, generate_groq
from sources.local_compute import (
    ComputationResult,
    compare_complexity,
    evaluate_arithmetic,
    evaluate_unit_conversion,
    verify_computational_claim,
)
from sources.openalex_client import OpenAlexClient, OpenAlexWork, search_openalex
from sources.unpaywall_client import UnpaywallClient, UnpaywallPaper, fetch_unpaywall_pdf
from sources.wolfram_client import WolframAlphaClient, WolframResult, query_wolfram

__all__ = [
    "GitHubClient",
    "GitHubRepoHealth",
    "fetch_repo_health",
    "UnpaywallClient",
    "UnpaywallPaper",
    "fetch_unpaywall_pdf",
    "CoreClient",
    "CorePaper",
    "search_core",
    "GroqClient",
    "generate_groq",
    "OpenAlexClient",
    "OpenAlexWork",
    "search_openalex",
    "CrossrefClient",
    "CrossrefWork",
    "search_crossref",
    "WolframAlphaClient",
    "WolframResult",
    "query_wolfram",
    "ComputationResult",
    "evaluate_arithmetic",
    "evaluate_unit_conversion",
    "compare_complexity",
    "verify_computational_claim",
]
