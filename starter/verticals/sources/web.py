"""The one HTTP helper source agents share: a timeout, a plain user agent, raise on errors."""

import html
import re

import httpx2 as httpx

UA = {"User-Agent": "Mozilla/5.0 (X-ray provenance check; hackathon)"}
TIMEOUT = 15


def get_text(url: str, params: dict | None = None) -> str:
    r = httpx.get(url, params=params, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.text


def visible_text(page: str) -> str:
    """The words a reader sees: scripts, styles and tags removed, whitespace collapsed."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def get_bytes(url: str) -> bytes:
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.content
