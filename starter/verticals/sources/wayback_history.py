"""Dated changes in archived adverts, grounded in raw Internet Archive documents."""

import ipaddress
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import httpx2

from starter.core.xray import Evidence, Place, now
from starter.verticals.sources.listing_history import parse_advert
from starter.verticals.sources.web import TIMEOUT, UA, visible_text

NAME = "wayback_history"
SOURCE = "Internet Archive Wayback Machine"
CDX_URL = "https://web.archive.org/cdx/search/cdx"
MAX_URLS = 4
MAX_CAPTURES = 6
MAX_CDX_BYTES = 2_000_000
MAX_HTML_BYTES = 5_000_000
_TIMESTAMP = re.compile(r"^\d{14}$")


def parse_cdx(payload) -> list[dict]:
    """Parse CDX JSON, retaining a bounded latest sample of distinct HTML versions."""
    if isinstance(payload, (str, bytes, bytearray)):
        payload = json.loads(payload)
    if not isinstance(payload, list):
        return []
    headers = None
    rows = payload
    if rows and isinstance(rows[0], list) and "timestamp" in rows[0]:
        headers, rows = rows[0], rows[1:]
    found, seen = [], set()
    for row in rows:
        if isinstance(row, dict):
            item = row
        elif headers and isinstance(row, list) and len(row) == len(headers):
            item = dict(zip(headers, row, strict=True))
        else:
            continue
        stamp, original = str(item.get("timestamp", "")), str(item.get("original", ""))
        if not _TIMESTAMP.fullmatch(stamp) or not original.startswith("https://"):
            continue
        if item.get("statuscode") not in (None, "200", 200):
            continue
        if item.get("mimetype") not in (None, "text/html", "application/xhtml+xml"):
            continue
        key = (stamp, original, str(item.get("digest", "")))
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {"timestamp": stamp, "original": original, "digest": str(item.get("digest", ""))}
        )
    found.sort(key=lambda x: (x["timestamp"], x["original"]))
    distinct, digests = [], set()
    for capture in reversed(found):
        digest = capture["digest"]
        if digest and digest in digests:
            continue
        if digest:
            digests.add(digest)
        distinct.append(capture)
        if len(distinct) >= MAX_CAPTURES:
            break
    return list(reversed(distinct))


def replay_url(capture: dict) -> str:
    """Raw replay URL tied to the exact CDX timestamp and original URL."""
    original = quote(capture["original"], safe=":/?=&%#")
    return f"https://web.archive.org/web/{capture['timestamp']}id_/{original}"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _identity_matches(place: Place, text: str) -> bool:
    """Require exact flat/building/street tokens and postcode, not a nearby address."""
    normalized_text = _norm(text)
    parts = [part.strip() for part in (place.address or "").split(",") if part.strip()]
    if parts:
        parts[0] = re.sub(r"^lot\s+\d+[a-z]?\s+", "", parts[0], flags=re.I).strip()
    tokens = []
    flat = re.search(r"\bflat\s*(\d+[a-z]?)\b", parts[0], re.I) if parts else None
    street_index = next(
        (i for i, part in enumerate(parts) if re.match(r"^\d+[a-z]?\s+\w", part, re.I)), None
    )
    if flat and street_index is not None:
        tokens.append(_norm(f"Flat {flat.group(1)}"))
        # Comma-separated components between flat and numbered street are a
        # building name, when present, and must also match.
        tokens.extend(_norm(part) for part in parts[1:street_index] if _norm(part))
        tokens.append(_norm(parts[street_index]))
    elif parts and re.match(r"^\d+[a-z]?\s+\w", parts[0], re.I):
        # For houses, keep number + street, not locality/city after the comma.
        tokens.append(_norm(parts[0]))
    postcode = _norm(place.postcode)
    return bool(
        tokens
        and postcode
        and all(token and token in normalized_text for token in tokens)
        and postcode in normalized_text
    )


def _role(field: str, matched: str) -> str:
    if field == "price":
        m = re.match(r"\s*(Sold(?: Prior| After)?|Guide|Unsold|Withdrawn|Postponed)", matched, re.I)
        return re.sub(r"\s+", "_", m.group(1).lower()) if m else "unspecified"
    return "advert"


def _history_field(field: str, role: str, unit: str | None) -> str:
    if field == "price":
        basis = "asking" if role == "guide" else "sold" if role.startswith("sold") else role
        return f"advert_{basis}_price_gbp"
    if field == "rent_pcm":
        return "advert_rent_pcm_gbp"
    if field == "rent_pa":
        return "advert_rent_pa_gbp"
    if field == "floor_area":
        return "floor_area_sqft" if unit == "sq ft" else "floor_area_m2"
    return field


def snapshot_observations(place: Place, html: str, captured_at: str) -> list[dict]:
    """Extract dated fields only when full property identity is visible."""
    text = visible_text(html)
    if not _identity_matches(place, text):
        return []
    observations = []
    for field, (value, unit, span) in parse_advert(text).items():
        role = _role(field, span)
        observations.append(
            {
                "field": _history_field(field, role, unit),
                "value": value,
                "unit": unit,
                "span": span,
                "role": role,
                "captured_at": captured_at,
                "text": text,
            }
        )
    return observations


def _safe_public_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            return False
        host = p.hostname.lower().rstrip(".")
        if (
            host in ("localhost", "localhost.localdomain")
            or host.endswith(".localhost")
            or host.endswith(".local")
        ):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return True
    except (TypeError, ValueError):
        return False


def _history_urls(listing: dict) -> list[str]:
    candidates = [listing.get("url", ""), *(listing.get("history_urls") or [])]
    urls = []
    for url in candidates:
        if isinstance(url, str) and _safe_public_url(url) and url not in urls:
            urls.append(url)
        if len(urls) >= MAX_URLS:
            break
    return urls


def _exact_original(capture: dict, requested_url: str) -> bool:
    return capture.get("original") == requested_url


def _dt(stamp: str) -> str:
    return (
        datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC).isoformat(timespec="seconds")
    )


def _response_is_exact_capture(response, stamp: str) -> bool:
    """Reject live fallbacks, different captures, and redirects outside Wayback."""
    final = urlsplit(str(response.url))
    if final.hostname != "web.archive.org":
        return False
    m = re.search(r"/web/(\d{14})(?:id_)?/", final.path)
    url_stamp = m.group(1) if m else None
    header = response.headers.get("Memento-Datetime") or response.headers.get("memento-datetime")
    header_stamp = None
    if header:
        try:
            header_stamp = parsedate_to_datetime(header).astimezone(UTC).strftime("%Y%m%d%H%M%S")
        except (TypeError, ValueError, OverflowError):
            return False
    return (url_stamp == stamp) and (header_stamp in (None, stamp))


def _collect(
    place: Place, listing: dict, *, get=None, land_fn=None, ground_fn=None
) -> list[Evidence]:
    """Fetch and land each bounded raw response, then emit scalar dated facts."""
    get = get or httpx2.get
    if land_fn is None:
        from starter.core.ingest import land

        land_fn = land
    if ground_fn is None:
        from starter.core.ingest import decoded_text, ground

        ground_fn = ground
    else:
        from starter.core.ingest import decoded_text
    timeline = []
    for requested_url in _history_urls(listing):
        params = {
            "url": requested_url,
            "output": "json",
            "fl": "timestamp,original,mimetype,statuscode,digest",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "collapse": "digest",
            "sort": "reverse",
            "limit": "50",
            "gzip": "false",
        }
        cdx_response = get(
            CDX_URL, params=params, headers=UA, timeout=TIMEOUT, follow_redirects=False
        )
        cdx_response.raise_for_status()
        raw_cdx = cdx_response.content
        if len(raw_cdx) > MAX_CDX_BYTES:
            continue
        land_fn(
            listing,
            raw=raw_cdx,
            source_url=str(cdx_response.url),
            agent=NAME,
            content_type="application/json",
            fetched_at=now(),
        )
        captures = [c for c in parse_cdx(raw_cdx) if _exact_original(c, requested_url)]
        for capture in captures:
            archived_url = replay_url(capture)
            response = get(archived_url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            raw_html = response.content
            if len(raw_html) > MAX_HTML_BYTES:
                continue
            fetched_at = now()
            content_type = (
                response.headers.get("content-type", "text/html").split(";", 1)[0].lower()
            )
            document = land_fn(
                listing,
                raw=raw_html,
                source_url=str(response.url),
                agent=NAME,
                content_type=content_type,
                fetched_at=fetched_at,
            )
            if not _response_is_exact_capture(response, capture["timestamp"]):
                continue
            if content_type not in ("text/html", "application/xhtml+xml"):
                continue
            text = response.text
            if not text and raw_html:
                text = raw_html.decode("utf-8", errors="replace")
            stamp = capture["timestamp"]
            for observation in snapshot_observations(place, text, _dt(stamp)):
                timeline.append((stamp, observation, document))
    timeline.sort(key=lambda item: item[0])
    previous = {}
    evidence = []
    for stamp, observation, document in timeline:
        field = observation["field"]
        key = (field, observation["unit"], observation["role"])
        if key in previous and previous[key]["value"] == observation["value"]:
            continue
        document_text = decoded_text(document)
        if document_text is None:
            continue
        span = ground_fn(document_text, observation["span"])
        if span is None:
            continue
        evidence.append(
            Evidence(
                id=f"ev-wayback-{listing['listing_id']}-{field}-{stamp}-{document.sha256[:10]}",
                place_id=place.id,
                field=field,
                value=observation["value"],
                unit=observation["unit"],
                source_name=SOURCE,
                source_url=document.url,
                doc_span=span.quote,
                fetched_at=now(),
                agent=NAME,
                document_id=document.id,
                span=span,
                observed_at=_dt(stamp),
            )
        )
        previous[key] = observation
    return evidence


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    """Wayback supplies contextual evidence only; no captures means no assertions."""
    if listing.get("offline"):
        # Fixtures intentionally contain no archived snapshots.
        return [], []
    return [], _collect(place, listing)
