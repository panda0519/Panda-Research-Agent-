"""Unit tests for the 7 external client modules, local compute engine, and API key manager."""
import asyncio
import os
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from sources.github_client import GitHubClient, GitHubRepoHealth, fetch_repo_health
from sources.unpaywall_client import UnpaywallClient, UnpaywallPaper, fetch_unpaywall_pdf
from sources.core_client import CoreClient, CorePaper, search_core
from sources.groq_client import GroqClient, generate_groq
from sources.openalex_client import OpenAlexClient, OpenAlexWork, reconstruct_abstract, search_openalex
from sources.crossref_client import CrossrefClient, CrossrefWork, search_crossref
from sources.wolfram_client import WolframAlphaClient, WolframResult, query_wolfram
from sources.local_compute import (
    ComputationResult,
    compare_complexity,
    evaluate_arithmetic,
    evaluate_unit_conversion,
    parse_complexity_rank,
    verify_computational_claim,
)
from api_key_manager import (
    KEY_DEFINITIONS,
    mask_api_key,
    test_key_connection as run_test_key_connection,
)


# ===========================================================================
# 1. GitHubClient Tests
# ===========================================================================

def test_github_parse_identifier():
    assert GitHubClient.parse_repo_identifier("openai/whisper") == ("openai", "whisper")
    assert GitHubClient.parse_repo_identifier("https://github.com/pyannote/pyannote-audio") == ("pyannote", "pyannote-audio")
    assert GitHubClient.parse_repo_identifier("https://github.com/huggingface/transformers.git") == ("huggingface", "transformers")
    assert GitHubClient.parse_repo_identifier("invalid_single_string") is None


def test_github_repo_health_success():
    client = GitHubClient(token="ghp_test_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "owner": {"login": "pyannote"},
        "name": "pyannote-audio",
        "full_name": "pyannote/pyannote-audio",
        "stargazers_count": 5200,
        "forks_count": 620,
        "open_issues_count": 45,
        "subscribers_count": 95,
        "archived": False,
        "fork": False,
        "default_branch": "develop",
        "pushed_at": "2024-03-01T12:00:00Z",
        "license": {"spdx_id": "MIT"},
        "description": "Neural building blocks for speaker diarization",
        "language": "Python",
        "topics": ["speaker-diarization", "voice-activity-detection"],
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = asyncio.run(client.get_repo_health("pyannote/pyannote-audio"))
        assert health is not None
        assert health.owner == "pyannote"
        assert health.repo == "pyannote-audio"
        assert health.stars == 5200
        assert health.forks == 620
        assert health.license_spdx == "MIT"
        assert health.is_archived is False
        assert health.is_authenticated is True


def test_github_repo_health_404():
    client = GitHubClient(token="")
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = asyncio.run(client.get_repo_health("nonexistent/repo-xyz"))
        assert health is None


def test_github_repo_health_429_backoff():
    client = GitHubClient()
    mock_429 = MagicMock(status_code=429)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch("asyncio.sleep", new_callable=AsyncMock):
        mock_get.return_value = mock_429
        health = asyncio.run(client.get_repo_health("pyannote/pyannote-audio"))
        assert health is None
        assert mock_get.call_count == 3


def test_github_repo_health_timeout():
    client = GitHubClient()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Timeout")
        health = asyncio.run(client.get_repo_health("pyannote/pyannote-audio"))
        assert health is None


# ===========================================================================
# 2. UnpaywallClient Tests
# ===========================================================================

def test_unpaywall_clean_doi():
    assert UnpaywallClient.clean_doi("10.1038/nature12373") == "10.1038/nature12373"
    assert UnpaywallClient.clean_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert UnpaywallClient.clean_doi("not-a-doi") is None


def test_unpaywall_missing_email():
    client = UnpaywallClient(email="")
    res = asyncio.run(client.get_paper_by_doi("10.1038/nature12373"))
    assert res is None


def test_unpaywall_success():
    client = UnpaywallClient(email="researcher@example.com")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "doi": "10.1038/nature12373",
        "is_oa": True,
        "title": "Quantum Teleportation Across 100km",
        "best_oa_location": {
            "url": "https://nature.com/articles/nature12373.pdf",
            "url_for_pdf": "https://nature.com/articles/nature12373.pdf",
            "url_for_landing_page": "https://nature.com/articles/nature12373",
            "host_type": "publisher",
            "license": "cc-by",
        },
        "year": 2023,
        "journal_name": "Nature",
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        paper = asyncio.run(client.get_paper_by_doi("10.1038/nature12373"))
        assert paper is not None
        assert paper.is_oa is True
        assert paper.pdf_url == "https://nature.com/articles/nature12373.pdf"
        assert paper.journal_name == "Nature"


def test_unpaywall_404_and_timeout():
    client = UnpaywallClient(email="researcher@example.com")

    # 404
    mock_404 = MagicMock(status_code=404)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_404
        assert asyncio.run(client.get_paper_by_doi("10.1038/nonexistent")) is None

    # Timeout
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Timeout")
        assert asyncio.run(client.get_paper_by_doi("10.1038/nature12373")) is None


# ===========================================================================
# 3. CoreClient Tests
# ===========================================================================

def test_core_missing_api_key():
    client = CoreClient(api_key="")
    assert asyncio.run(client.search_works("speech diarization")) == []


def test_core_search_success():
    client = CoreClient(api_key="core_test_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "id": 123456,
                "doi": "10.1145/3383583.3398539",
                "title": "Fast Clustering for Speaker Diarization",
                "abstract": "We present an ultra fast spectral clustering algorithm.",
                "downloadUrl": "https://core.ac.uk/download/pdf/123456.pdf",
                "sourceFulltextUrls": ["https://repo.ac.uk/paper.pdf"],
                "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
                "yearPublished": 2022,
                "publisher": "ACM",
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        results = asyncio.run(client.search_works("speaker diarization", limit=3))
        assert len(results) == 1
        paper = results[0]
        assert paper.core_id == "123456"
        assert paper.title == "Fast Clustering for Speaker Diarization"
        assert paper.download_url == "https://core.ac.uk/download/pdf/123456.pdf"
        assert paper.authors == ["Alice Smith", "Bob Jones"]
        assert paper.year == 2022


def test_core_search_error_and_rate_limit():
    client = CoreClient(api_key="core_test_key")

    mock_401 = MagicMock(status_code=401)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_401
        assert asyncio.run(client.search_works("query")) == []

    mock_429 = MagicMock(status_code=429)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch("asyncio.sleep", new_callable=AsyncMock):
        mock_get.return_value = mock_429
        assert asyncio.run(client.search_works("query")) == []


# ===========================================================================
# 4. GroqClient Tests
# ===========================================================================

def test_groq_missing_api_key():
    client = GroqClient(api_key="")
    assert asyncio.run(client.generate("Verify claim: 2+2=4")) is None


def test_groq_generate_success():
    client = GroqClient(api_key="gsk_test_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '[{"claim_text": "PyAnnote achieves 5% DER", "status": "CONFIRMED"}]',
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = asyncio.run(client.generate("Verify this claim"))
        assert res is not None
        assert "CONFIRMED" in res


def test_groq_errors_and_timeout():
    client = GroqClient(api_key="gsk_test_key")

    # 401
    mock_401 = MagicMock(status_code=401)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_401
        assert asyncio.run(client.generate("Prompt")) is None

    # Timeout
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")
        assert asyncio.run(client.generate("Prompt")) is None


# ===========================================================================
# 5. OpenAlexClient Tests
# ===========================================================================

def test_openalex_abstract_reconstruction():
    inverted_index = {
        "Neural": [0],
        "speech": [1],
        "diarization": [2],
        "achieves": [3],
        "high": [4],
        "accuracy.": [5],
    }
    reconstructed = reconstruct_abstract(inverted_index)
    assert reconstructed == "Neural speech diarization achieves high accuracy."


def test_openalex_search_success():
    client = OpenAlexClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "id": "https://openalex.org/W123456789",
                "doi": "https://doi.org/10.1109/taslp.2021.3120593",
                "title": "End-to-End Neural Diarization",
                "publication_year": 2021,
                "cited_by_count": 184,
                "authorships": [{"author": {"display_name": "Shota Horiguchi"}}],
                "concepts": [{"display_name": "Speaker Diarization"}, {"display_name": "Neural Network"}],
                "primary_location": {
                    "landing_page_url": "https://ieeexplore.ieee.org/document/9583210",
                    "pdf_url": "https://arxiv.org/pdf/2105.09355.pdf",
                },
                "open_access": {"is_oa": True},
                "abstract_inverted_index": {"End-to-end": [0], "neural": [1], "diarization": [2]},
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        results = asyncio.run(client.search_works("neural diarization", limit=3))
        assert len(results) == 1
        work = results[0]
        assert work.title == "End-to-End Neural Diarization"
        assert work.cited_by_count == 184
        assert work.concepts == ["Speaker Diarization", "Neural Network"]
        assert work.abstract == "End-to-end neural diarization"
        assert work.is_oa is True


# ===========================================================================
# 6. CrossrefClient Tests
# ===========================================================================

def test_crossref_search_success():
    client = CrossrefClient(mailto="researcher@example.com")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {
            "items": [
                {
                    "DOI": "10.1016/j.specom.2020.10.002",
                    "title": ["A Review of Speaker Diarization"],
                    "author": [{"given": "Hervé", "family": "Bredin"}],
                    "issued": {"date-parts": [[2021, 1, 15]]},
                    "container-title": ["Speech Communication"],
                    "is-referenced-by-count": 312,
                    "URL": "http://dx.doi.org/10.1016/j.specom.2020.10.002",
                    "type": "journal-article",
                    "abstract": "<jats:p>Speaker diarization is the task of segmenting audio.</jats:p>",
                }
            ]
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        results = asyncio.run(client.search_works("speaker diarization bredin", limit=3))
        assert len(results) == 1
        work = results[0]
        assert work.doi == "10.1016/j.specom.2020.10.002"
        assert work.title == "A Review of Speaker Diarization"
        assert work.authors == ["Hervé Bredin"]
        assert work.year == 2021
        assert work.container_title == "Speech Communication"
        assert work.is_referenced_by_count == 312
        assert work.abstract == "Speaker diarization is the task of segmenting audio."


# ===========================================================================
# 7. WolframAlphaClient Tests
# ===========================================================================

def test_wolfram_missing_app_id():
    client = WolframAlphaClient(app_id="")
    assert asyncio.run(client.query("2 + 2")) is None


def test_wolfram_success():
    client = WolframAlphaClient(app_id="TEST_APP_ID")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "4"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = asyncio.run(client.query("2 + 2"))
        assert res is not None
        assert res.is_success is True
        assert res.result == "4"
        assert res.call_count_in_run == 1


def test_wolfram_hard_cap_enforcement():
    client = WolframAlphaClient(app_id="TEST_APP_ID", max_calls_per_run=3)
    mock_resp = MagicMock(status_code=200, text="42")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        # Calls 1, 2, 3 should succeed
        for i in range(1, 4):
            res = asyncio.run(client.query(f"{i} + {i}"))
            assert res is not None
            assert res.call_count_in_run == i

        # Call 4 should be rejected due to hard cap
        res_blocked = asyncio.run(client.query("4 + 4"))
        assert res_blocked is None
        assert mock_get.call_count == 3


# ===========================================================================
# 8. LocalCompute Engine Tests
# ===========================================================================

def test_local_compute_arithmetic():
    assert evaluate_arithmetic("10 + 20") == 30
    assert evaluate_arithmetic("100 * 5 - 50 / 2") == 475.0
    assert evaluate_arithmetic("2^8") == 256
    assert evaluate_arithmetic("1024 * 768") == 786432
    assert evaluate_arithmetic("10 / 0") is None
    assert evaluate_arithmetic("invalid(expr)") is None


def test_local_compute_unit_conversions():
    # Data size
    assert evaluate_unit_conversion(1024, "KB", "MB") == 1.0
    assert evaluate_unit_conversion(2, "GB", "MB") == 2048.0
    assert evaluate_unit_conversion(8, "bytes", "bits") is not None

    # Time
    assert evaluate_unit_conversion(1000, "ms", "s") == 1.0
    assert evaluate_unit_conversion(120, "s", "min") == 2.0
    assert evaluate_unit_conversion(1, "hr", "s") == 3600.0

    # Frequency
    assert evaluate_unit_conversion(1000, "MHz", "GHz") == 1.0


def test_local_compute_complexity_hierarchy():
    # Ranks
    r_const, _ = parse_complexity_rank("O(1)")
    r_log, _ = parse_complexity_rank("O(log n)")
    r_linear, _ = parse_complexity_rank("O(n)")
    r_linearithmic, _ = parse_complexity_rank("O(n log n)")
    r_quad, _ = parse_complexity_rank("O(n^2)")
    r_exp, _ = parse_complexity_rank("O(2^n)")
    r_fact, _ = parse_complexity_rank("O(n!)")

    assert r_const < r_log < r_linear < r_linearithmic < r_quad < r_exp < r_fact

    # Comparison helper
    assert compare_complexity("O(n log n)", "O(n^2)") == -1  # O(n log n) is lower/better than O(n^2)
    assert compare_complexity("O(n^2)", "O(n log n)") == 1   # O(n^2) is higher/worse than O(n log n)
    assert compare_complexity("O(n)", "O(n)") == 0


def test_verify_computational_claims():
    # Complexity reduction claim
    c1 = verify_computational_claim("Proposed architecture reduces complexity from O(n^2) to O(n log n)")
    assert c1 is not None
    assert c1.is_verified is True
    assert c1.claim_type == "complexity"

    # Percentage reduction claim
    c2 = verify_computational_claim("Decreases latency from 200ms to 50ms (a 75% reduction)")
    assert c2 is not None
    assert c2.is_verified is True
    assert c2.computed_value == 75.0

    # False percentage reduction claim
    c3 = verify_computational_claim("Decreases latency from 200ms to 150ms (a 50% reduction)")
    assert c3 is not None
    assert c3.is_verified is False  # actual is 25%, claimed 50%

    # Arithmetic claim
    c4 = verify_computational_claim("Total parameters required: 1024 * 768 = 786432")
    assert c4 is not None
    assert c4.is_verified is True


# ===========================================================================
# 9. API Key Manager Tests
# ===========================================================================

def test_api_key_manager_key_definitions():
    assert "GITHUB_TOKEN" in KEY_DEFINITIONS
    assert "UNPAYWALL_EMAIL" in KEY_DEFINITIONS
    assert "CORE_API_KEY" in KEY_DEFINITIONS
    assert "GROQ_API_KEY" in KEY_DEFINITIONS
    assert "OPENALEX_API_KEY" in KEY_DEFINITIONS
    assert "CROSSREF_MAILTO" in KEY_DEFINITIONS
    assert "WOLFRAM_APP_ID" in KEY_DEFINITIONS

    # Non-secret emails
    assert KEY_DEFINITIONS["UNPAYWALL_EMAIL"]["is_secret"] is False
    assert KEY_DEFINITIONS["CROSSREF_MAILTO"]["is_secret"] is False
    assert KEY_DEFINITIONS["GROQ_API_KEY"]["is_secret"] is True


def test_mask_api_key_secret_vs_non_secret():
    # Secret key
    assert mask_api_key("sk-ant-api03-abcdefghijklmnop", is_secret=True).startswith("sk-ant")
    assert "•" in mask_api_key("sk-ant-api03-abcdefghijklmnop", is_secret=True)

    # Non-secret email
    email = "researcher@example.com"
    assert mask_api_key(email, is_secret=False) == email


def test_key_connection_tests():
    # Unpaywall email format check
    ok, code, msg = run_test_key_connection("UNPAYWALL_EMAIL", "invalid-email")
    assert ok is False
    assert code == 400

    # Empty key
    ok, code, msg = run_test_key_connection("GITHUB_TOKEN", "")
    assert ok is False
