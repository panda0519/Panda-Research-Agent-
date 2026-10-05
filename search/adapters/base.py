"""Base class and common types for search engine adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    engine: str
    score: float = 1.0
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSearchAdapter:
    name: str = "base"

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        raise NotImplementedError("Subclasses must implement search")
