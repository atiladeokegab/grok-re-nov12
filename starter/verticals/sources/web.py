"""The one HTTP helper source agents share: a timeout, a plain user agent, raise on errors."""

import html
import re
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx2 as httpx

from starter.core.errors import SourceOff

UA = {"User-Agent": "Mozilla/5.0 (X-ray provenance check; hackathon)"}
TIMEOUT = 8  # under the X-ray's 10 s budget (xray.BUDGET_S)
MAX_HOPS = 5


def get_text(
    url: str, params: dict | None = None, allow: Callable[[str], bool] | None = None
) -> str:
    """With `allow(url)`, redirects are followed by hand and every hop is checked first, so an
    allowed site cannot bounce the fetch to an internal address (SSRF); a refused hop is off."""
    if allow is None:
        r = httpx.get(url, params=params, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    else:
        for _ in range(MAX_HOPS + 1):
            if not allow(url):
                raise SourceOff(f"redirected off the advert site, to {urlparse(url).hostname}")
            r = httpx.get(url, params=params, headers=UA, timeout=TIMEOUT)
            if not r.is_redirect:
                break
            url, params = urljoin(str(r.url), r.headers["location"]), None
        else:
            raise SourceOff(f"more than {MAX_HOPS} redirects")
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
