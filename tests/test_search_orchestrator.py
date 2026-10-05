import asyncio
from search.adapters.base import BaseSearchAdapter, SearchResult
from search.orchestrator import SearchOrchestrator
from search.url_normalizer import extract_domain, normalize_url


def test_url_normalization():
    assert normalize_url("http://www.example.com/path?foo=bar#section") == "https://example.com/path"
    assert normalize_url("https://example.com/path/") == "https://example.com/path"
    assert normalize_url("example.com/article") == "https://example.com/article"
    assert normalize_url("http://WWW.Sub.Domain.org/test/") == "https://sub.domain.org/test"


def test_domain_extraction():
    assert extract_domain("https://www.github.com/torvalds/linux") == "github.com"
    assert extract_domain("http://arxiv.org/abs/2301.12345") == "arxiv.org"


class FakeAdapter1(BaseSearchAdapter):
    name = "engine1"

    async def search(self, query: str, max_results: int = 5):
        return [
            SearchResult(
                url="http://www.example.com/paper?id=1",
                title="Example Paper Title",
                snippet="Snippet from engine 1",
                engine=self.name,
            ),
            SearchResult(
                url="https://engine1-only.org/doc",
                title="Engine 1 Only",
                snippet="E1 content",
                engine=self.name,
            ),
        ]


class FakeAdapter2(BaseSearchAdapter):
    name = "engine2"

    async def search(self, query: str, max_results: int = 5):
        return [
            SearchResult(
                url="https://example.com/paper#top",
                title="Example Paper Better Title",
                snippet="Longer richer snippet from engine 2",
                engine=self.name,
            ),
            SearchResult(
                url="https://engine2-only.org/guide",
                title="Engine 2 Only",
                snippet="E2 content",
                engine=self.name,
            ),
        ]


class FailingAdapter(BaseSearchAdapter):
    name = "failing_engine"

    async def search(self, query: str, max_results: int = 5):
        raise ConnectionError("Network unreachable")


def test_orchestrator_merges_and_deduplicates():
    orchestrator = SearchOrchestrator(adapters=[FakeAdapter1(), FakeAdapter2()])
    sources = asyncio.run(orchestrator.search("test query"))

    # We should have 3 unique URLs: example.com/paper, engine1-only.org/doc, engine2-only.org/guide
    assert len(sources) == 3

    # Check the deduplicated multi-engine source
    multi_source = next(s for s in sources if "example.com" in s.url)
    assert set(multi_source.engines) == {"engine1", "engine2"}
    assert multi_source.trust_score > 1.0  # Agreement bonus
    assert "Longer richer snippet" in multi_source.snippet  # Richer snippet selected


def test_orchestrator_fault_tolerance():
    orchestrator = SearchOrchestrator(adapters=[FakeAdapter1(), FailingAdapter()])
    sources = asyncio.run(orchestrator.search("test query"))

    # Should still succeed with results from FakeAdapter1
    assert len(sources) == 2
    assert any(s.url.startswith("https://engine1-only.org") for s in sources)
