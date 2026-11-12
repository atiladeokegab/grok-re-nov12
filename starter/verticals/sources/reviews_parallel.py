"""Attributed search excerpts; a search hit does not establish a tenant's identity."""

import ipaddress
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from starter.core.xray import Claim, Evidence, Place

NAME = "reviews_parallel"
FIXTURE = {"results": []}


def _citation_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme not in {"https", "http"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or any(char.isspace() or ord(char) < 32 for char in url)
        ):
            return False
        if parsed.port == 0:
            return False
        host = host.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def review_excerpts(response: dict, allowed_urls: set[str] | None = None) -> list[dict]:
    if response.get("error") or response.get("errors"):
        raise ValueError("Parallel could not extract source excerpts")
    reviews = []
    seen = set()
    for result in response.get("results", []):
        url = result.get("url", "")
        if (
            not _citation_url(url)
            or url in seen
            or (allowed_urls is not None and url not in allowed_urls)
        ):
            continue
        excerpts = [text for text in result.get("excerpts", []) if isinstance(text, str)]
        if not excerpts or not excerpts[0].strip():
            continue
        seen.add(url)
        reviews.append(
            {
                "url": url,
                "title": result.get("title", ""),
                "excerpt": " ".join(excerpts[0].split()[:25]),
                "scope": "Search result; building and author identity require verification",
            }
        )
    return reviews


def ingest(place: "Place", listing: dict) -> tuple[list["Claim"], list["Evidence"]]:
    from starter.core.xray import Evidence

    fixture = (listing.get("fixture") or {}).get(NAME) if listing.get("offline") else None
    key = os.environ.get("PARALLEL_API_KEY")
    if fixture is None and (listing.get("offline") or not key):
        return [], []
    if fixture is not None:
        response = fixture
    else:
        import httpx2 as httpx

        search = httpx.post(
            "https://api.parallel.ai/v1/search",
            headers={"x-api-key": key},
            json={
                "objective": "Find attributed first-hand resident reviews of this exact property. "
                "Keep other buildings and agent-wide reviews distinguishable.",
                "search_queries": [f'"{place.address}" "{place.postcode}" tenant reviews'],
                "mode": "fast",
                "advanced_settings": {"max_results": 5},
            },
            timeout=15,
        )
        search.raise_for_status()
        search_data = search.json()
        if search_data.get("error") or search_data.get("errors"):
            raise ValueError("Parallel search failed")
        urls = list(
            dict.fromkeys(
                result["url"]
                for result in search_data.get("results", [])
                if _citation_url(result.get("url", ""))
            )
        )[:2]
        allowed_urls = set(urls)
        response = (
            httpx.post(
                "https://api.parallel.ai/v1/extract",
                headers={"x-api-key": key},
                json={
                    "urls": urls,
                    "objective": "Extract brief first-hand tenant comments specifically about this "
                    "property. Keep building-level scope and authorship unverified.",
                    "advanced_settings": {"full_content": False},
                },
                timeout=15,
            )
            if urls
            else None
        )
        if response is None:
            response = {"results": []}
        else:
            response.raise_for_status()
            response = response.json()
    fetched_at = (fixture or {}).get("fetched_at") or datetime.now(UTC).isoformat()
    return [], [
        Evidence(
            id=f"ev-{NAME}-{listing['listing_id']}-tenant_reviews-{index}",
            place_id=place.id,
            field="tenant_reviews",
            value=review,
            source_name="Parallel Search + Extract",
            source_url=review["url"],
            doc_span=(
                f"Parallel Search/Extract excerpt: {review['excerpt']} "
                f"(source URL: {review['url']}). "
                "Exact-building scope and author identity are unverified."
            ),
            fetched_at=fetched_at,
            agent=NAME,
        )
        for index, review in enumerate(
            review_excerpts(response, allowed_urls if fixture is None else None)
        )
    ]
