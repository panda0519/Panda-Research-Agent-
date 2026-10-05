from search.adapters.duckduckgo_adapter import DuckDuckGoSearchAdapter


SAMPLE_DDG_HTML = """
<html>
<body>
<div class="results">
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fpyannote%2Fpyannote-audio">PyAnnote Audio: Neural Building Blocks</a>
    <a class="result__snippet">PyAnnote audio is an open-source toolkit written in Python for speaker diarization.</a>
  </div>
  <div class="result">
    <a class="result__a" href="https://arxiv.org/abs/2305.12345">Streaming Speech Diarization</a>
    <a class="result__snippet">Paper describing real-time transformer diarization.</a>
  </div>
</div>
</body>
</html>
"""


def test_duckduckgo_html_parsing():
    adapter = DuckDuckGoSearchAdapter()
    results = adapter._parse_html(SAMPLE_DDG_HTML, max_results=5)

    assert len(results) == 2
    assert results[0].url == "https://github.com/pyannote/pyannote-audio"
    assert "PyAnnote Audio" in results[0].title
    assert "open-source toolkit" in results[0].snippet
    assert results[0].engine == "duckduckgo"

    assert results[1].url == "https://arxiv.org/abs/2305.12345"
    assert "Streaming Speech Diarization" in results[1].title
