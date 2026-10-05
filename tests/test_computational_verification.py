"""Unit tests for Phase B5 Computational Claim Verification ladder in Layer2ClaimVerifier."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from blackboard import Blackboard, Source
from sources.groq_client import GroqClient
from sources.wolfram_client import WolframAlphaClient, WolframResult
from verification.layer2_claim import Layer2ClaimVerifier


def test_computational_verification_arithmetic_confirmed():
    bb = Blackboard(run_id="run_comp_1", topic="image processing")
    mock_groq = AsyncMock(spec=GroqClient)
    # LLM returns a claim with valid arithmetic
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Resolution buffer size is 1024 * 768 = 786432 pixels.",
            "cited_urls": [],
            "status": "UNSUPPORTED",
            "rationale": "Extracted from architecture spec."
        }
    ]"""

    verifier = Layer2ClaimVerifier(groq_client=mock_groq)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Buffer size calculation", bb))

    assert len(results) == 1
    assert results[0].status == "CONFIRMED"
    assert "[Deterministic Compute Verified: Arithmetic]" in results[0].rationale
    assert "786432" in results[0].rationale


def test_computational_verification_arithmetic_contradicted():
    bb = Blackboard(run_id="run_comp_2", topic="image processing")
    mock_groq = AsyncMock(spec=GroqClient)
    # LLM claims wrong arithmetic
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Resolution buffer size is 1024 * 768 = 999999 pixels.",
            "cited_urls": [],
            "status": "CONFIRMED",
            "rationale": "Claimed by agent."
        }
    ]"""

    verifier = Layer2ClaimVerifier(groq_client=mock_groq)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Buffer size calculation", bb))

    assert len(results) == 1
    assert results[0].status == "CONTRADICTED"
    assert "[Deterministic Compute Discrepancy]" in results[0].rationale
    assert "Computed 786432" in results[0].rationale


def test_computational_verification_complexity_reduction_confirmed():
    bb = Blackboard(run_id="run_comp_3", topic="sorting algorithm")
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Our algorithm reduces complexity from O(n^2) to O(n log n).",
            "cited_urls": [],
            "status": "NEEDS_HUMAN",
            "rationale": "Evaluation note."
        }
    ]"""

    verifier = Layer2ClaimVerifier(groq_client=mock_groq)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Complexity analysis", bb))

    assert len(results) == 1
    assert results[0].status == "CONFIRMED"
    assert "[Deterministic Compute Verified: Complexity]" in results[0].rationale


def test_computational_verification_complexity_regression_contradicted():
    bb = Blackboard(run_id="run_comp_4", topic="sorting algorithm")
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Our algorithm reduces complexity from O(n) to O(n^2).",
            "cited_urls": [],
            "status": "CONFIRMED",
            "rationale": "Claimed speedup."
        }
    ]"""

    verifier = Layer2ClaimVerifier(groq_client=mock_groq)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Complexity analysis", bb))

    assert len(results) == 1
    assert results[0].status == "CONTRADICTED"
    assert "[Deterministic Compute Discrepancy]" in results[0].rationale
    assert "O(n^2) is not lower complexity than O(n)" in results[0].rationale


def test_computational_verification_percentage_reduction():
    bb = Blackboard(run_id="run_comp_5", topic="latency optimization")
    mock_groq = AsyncMock(spec=GroqClient)
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Reduces inference latency from 200ms to 50ms (a 75% reduction).",
            "cited_urls": [],
            "status": "UNSUPPORTED",
            "rationale": "Benchmark results."
        }
    ]"""

    verifier = Layer2ClaimVerifier(groq_client=mock_groq)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Latency benchmark", bb))

    assert len(results) == 1
    assert results[0].status == "CONFIRMED"
    assert "[Deterministic Compute Verified: Percentage]" in results[0].rationale


def test_computational_verification_wolfram_alpha_integration():
    bb = Blackboard(run_id="run_comp_6", topic="scientific calculation")
    mock_groq = AsyncMock(spec=GroqClient)
    # Natural language scientific claim not covered by simple local regex
    mock_groq.generate.return_value = """[
        {
            "claim_text": "Speed of light in vacuum is approximately 299792458 m/s.",
            "cited_urls": [],
            "status": "NEEDS_HUMAN",
            "rationale": "Physical constant."
        }
    ]"""

    mock_wolfram = MagicMock(spec=WolframAlphaClient)
    mock_wolfram.app_id = "test-wolfram-app-id"
    mock_wolfram.query = AsyncMock(
        return_value=WolframResult(
            query="Speed of light in vacuum is approximately 299792458 m/s.",
            result="299792458 m/s (meters per second)",
            is_success=True,
            call_count_in_run=1,
        )
    )

    verifier = Layer2ClaimVerifier(groq_client=mock_groq, wolfram_client=mock_wolfram)
    results = asyncio.run(verifier.verify_claims("IdeatorAgent", "Physics constants", bb))

    assert len(results) == 1
    assert mock_wolfram.query.call_count == 1
    assert "[Wolfram Alpha Checked: 299792458 m/s" in results[0].rationale
