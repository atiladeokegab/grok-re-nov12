"""Cloud Vision web matches are evidence of reuse, never proof of fraud."""

import ipaddress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from starter.core.xray import Claim, Evidence, Place

NAME = "reverse_image"
FIXTURE = {"by_image": {}}
VISION_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


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


def web_matches(response: dict) -> list[dict]:
    """Ignore visual similarity: only indexed full/partial matches are attributable."""
    if response.get("error") or response.get("errors"):
        raise ValueError("Cloud Vision could not inspect this image")
    matches = []
    seen = set()
    for item in response.get("responses", []):
        if item.get("error"):
            raise ValueError("Cloud Vision could not inspect this image")
        for page in item.get("webDetection", {}).get("pagesWithMatchingImages", []):
            url = page.get("url", "")
            if not _citation_url(url) or url in seen:
                continue
            kind = "full" if page.get("fullMatchingImages") else "partial"
            if not page.get("fullMatchingImages") and not page.get("partialMatchingImages"):
                continue
            seen.add(url)
            matches.append({"url": url, "title": page.get("pageTitle", ""), "match_type": kind})
    return matches


def ingest(place: "Place", listing: dict) -> tuple[list["Claim"], list["Evidence"]]:
    from starter.core.xray import Evidence

    fixture = (listing.get("fixture") or {}).get(NAME) if listing.get("offline") else None
    evidence = []
    photos = listing.get("page", {}).get("photos", listing.get("photos", []))[:3]
    image_urls = [
        image_url
        for photo in photos
        if (image_url := (photo if isinstance(photo, str) else photo.get("url", "")))
        and _citation_url(image_url)
        and urlsplit(image_url).scheme == "https"
    ]
    credentials = None
    auth_request = None
    if fixture is None:
        if listing.get("offline") or not image_urls:
            return [], []
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
        from google.auth.transport.requests import Request

        try:
            credentials, _ = google.auth.default(scopes=[VISION_SCOPE])
        except DefaultCredentialsError:
            return [], []
        auth_request = Request()

    for index, image_url in enumerate(image_urls):
        if fixture is not None:
            response = fixture.get("by_image", {}).get(image_url, {"responses": []})
        else:
            import httpx2 as httpx

            headers = {}
            credentials.before_request(auth_request, "POST", VISION_URL, headers)
            result = httpx.post(
                VISION_URL,
                headers=headers,
                json={
                    "requests": [
                        {
                            "image": {"source": {"imageUri": image_url}},
                            "features": [{"type": "WEB_DETECTION", "maxResults": 5}],
                        }
                    ]
                },
                timeout=15,
            )
            result.raise_for_status()
            response = result.json()
        fetched_at = (fixture or {}).get("fetched_at") or datetime.now(UTC).isoformat()
        for match_index, match in enumerate(web_matches(response)):
            evidence.append(
                Evidence(
                    id=f"ev-{NAME}-{listing['listing_id']}-photo_reuse-{index}-{match_index}",
                    place_id=place.id,
                    field="photo_reuse",
                    value={
                        "image_url": image_url,
                        **match,
                        "interpretation": "Indexed image reuse; ownership and context unverified",
                    },
                    source_name="Google Cloud Vision Web Detection",
                    source_url=match["url"],
                    doc_span=(
                        f"Web Detection found a {match['match_type']} image match. "
                        "Reuse is observed; "
                        f"ownership, consent, and intent are unverified. Source: {match['url']}"
                    ),
                    fetched_at=fetched_at,
                    agent=NAME,
                )
            )
    return [], evidence
