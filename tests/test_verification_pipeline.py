import asyncio
from blackboard import Blackboard, Source, Solution, Gap, Feature
from verification.layer1_source import Layer1SourceVerifier
from verification.pipeline import VerificationPipeline
from verification.layer2_claim import Layer2ClaimVerifier
from verification.layer3_consistency import Layer3ConsistencyVerifier


def test_layer1_source_verification():
    verifier = Layer1SourceVerifier(
        config={
            "timeout_seconds": 1.0,
            "min_trust_score": 0.5,
            "disallowed_domains": ["spam.com"],
            "high_trust_domains": ["arxiv.org", "github.com"],
        }
    )

    sources = [
        # Disallowed domain
        Source(url="https://spam.com/article", title="Spam", snippet="Buy now", engines=["engine1"]),
        # High trust domain + multi engine
        Source(url="https://mock.arxiv.org/abs/2101.0001", title="ArXiv Paper", snippet="Valid research", engines=["engine1", "engine2"]),
        # Single engine mock
        Source(url="https://mock.example.com/guide", title="Guide", snippet="Some content", engines=["engine1"]),
    ]

    verified = asyncio.run(verifier.verify_sources(sources))

    # spam.com should be dropped
    assert len(verified) == 2
    assert not any("spam.com" in s.url for s in verified)

    arxiv_src = next(s for s in verified if "arxiv.org" in s.url)
    assert arxiv_src.trust_score > 1.2  # High trust domain + multi engine boost


def test_verification_badge_formatting():
    assert VerificationPipeline.format_badge("CONFIRMED", single_engine=False) == "`✓ confirmed`"
    assert VerificationPipeline.format_badge("CONFIRMED", single_engine=True) == "`✓ confirmed (⚠ single-source)`"
    assert VerificationPipeline.format_badge("CONTRADICTED") == "`✗ contradicted`"
    assert VerificationPipeline.format_badge("UNSUPPORTED") == "`⚠ unsupported`"
    assert VerificationPipeline.format_badge("NEEDS_HUMAN") == "`? unverified`"


def test_layer3_orphan_citation_detection():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bb.add_source(Source(url="https://example.com/verified-source", title="Verified", snippet="snippet"))

    # Solution references an unverified orphan URL
    bb.add_solution(
        Solution(
            name="Orphan Tool",
            category="commercial",
            description="A tool",
            sources=["https://example.com/orphan-url-not-on-blackboard"],
        )
    )

    verifier = Layer3ConsistencyVerifier()
    # Mock LLM generation to return no contradictions
    verifier.llm.generate = lambda **kwargs: "[]"

    issues = asyncio.run(verifier.verify_consistency(bb))
    assert len(issues) == 1
    assert "Orphan citation" in issues[0]
    assert "orphan-url-not-on-blackboard" in issues[0]
