import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from blackboard import Blackboard, ClaimVerification
from verification.layer2_claim import Layer2ClaimVerifier

def test_layer2_claim_verification_groq_fallback():
    bb = Blackboard(run_id="test_run", topic="test topic")

    # Mock Groq to fail first, then work
    mock_groq = AsyncMock()
    mock_groq.generate.return_value = '[{"claim_text": "Claim 1", "status": "CONFIRMED", "cited_urls": []}]'

    verifier = Layer2ClaimVerifier()
    verifier.groq = mock_groq

    # Mock LLM fallback
    with patch.object(verifier.llm, "generate", return_value='[{"claim_text": "Claim 1", "status": "CONFIRMED", "cited_urls": []}]') as mock_llm:
        # Scenario 1: Groq succeeds
        results = asyncio.run(verifier.verify_claims("AgentX", "Some text", bb))
        assert len(results) == 1
        assert results[0].claim_text == "Claim 1"
        assert mock_groq.generate.call_count == 1

        # Scenario 2: Groq fails (return None), LLM fallback
        mock_groq.generate.return_value = None
        results = asyncio.run(verifier.verify_claims("AgentX", "Some text", bb))
        assert len(results) == 1
        assert len(bb.claim_verifications) == 2  # 1 from before + 1 new on blackboard
        assert mock_llm.call_count == 1
