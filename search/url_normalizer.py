"""URL normalization and deduplication utilities."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Normalize URL for comparison and deduplication:
    - Normalizes scheme to https
    - Lowercases hostname
    - Strips 'www.' prefix
    - Strips query parameters and URL fragments
    - Strips trailing slashes from path
    """
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path = parsed.path.rstrip("/")
        # Reconstruct without query params, params, or fragments
        return urlunparse(("https", netloc, path, "", "", ""))
    except Exception:
        return url.strip().lower()


def extract_domain(url: str) -> str:
    """Extract registered domain or hostname from URL."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""
