import asyncio
from sources.web_scraper import WebScraper, clean_html


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Technical Documentation</title></head>
<body>
  <header><nav><a href="/home">Home</a></nav></header>
  <script>var x = 123; console.log(x);</script>
  <style>body { font-size: 14px; }</style>
  <article>
    <h1>Neural Diarization Engine</h1>
    <p>This is a high-performance streaming diarization system operating on 100ms frames.</p>
    <code>model.forward(audio_tensor)</code>
    <p>Empirical results demonstrate a 4.2% DER on DIHARD III.</p>
  </article>
  <footer><p>Copyright 2026</p></footer>
</body>
</html>
"""


def test_clean_html_strips_scripts_and_styles():
    cleaned = clean_html(SAMPLE_HTML)
    assert "Neural Diarization Engine" in cleaned
    assert "4.2% DER on DIHARD III" in cleaned
    assert "console.log" not in cleaned
    assert "font-size" not in cleaned
    assert "<script>" not in cleaned
    assert "<nav>" not in cleaned


def test_web_scraper_batch_empty():
    scraper = WebScraper()
    results = asyncio.run(scraper.scrape_urls_batch([]))
    assert results == {}
