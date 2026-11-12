"""Listing history: what the advert says now (claims, read from the live page with the exact
words as doc_span) against what the organisers' crawl recorded on its date (evidence). A field
the crawl recorded differently becomes a history entry and, in the reconciler, a flag.

Parsers cover auctionhouse.co.uk adverts (the crawl's E14 listings); another site's advert
yields no claims (status "empty"), never guessed ones.
"""

import re
from urllib.parse import urljoin, urlparse

from starter.core.errors import SourceOff
from starter.core.xray import Claim, Evidence, Place, now
from starter.verticals.sources.web import get_text, visible_text

NAME = "listing_history"
CRAWL = "Organisers' listings crawl"

# field -> (pattern on the advert's visible text, unit, value parser)
PATTERNS = {
    "price": (r"(?:Sold|Guide|Unsold|Sold Prior|Sold After)\s*\*?\s*£([\d,]+)", "GBP", "money"),
    "sale_status": (r"\b(Sold Prior|Sold After|Sold|Unsold|Withdrawn|Postponed)\s*£", None, "str"),
    "rent_pcm": (r"rent of £([\d,]+) per calendar month", "GBP/month", "money"),
    "rent_pa": (r"Producing £([\d,]+) Per Annum", "GBP/year", "money"),
    "energy_rating": (r"Energy Efficiency Rating \(EPC\) Current Rating ([A-G])\b", None, "str"),
    "property_type": (
        r"\b(Semi[- ]Detached|Detached|End[- ]Terrace|Mid[- ]Terrace|Terraced)\s+House",
        None,
        "str",
    ),
    "bedrooms": (r"\b(\w+) Bedrooms?\b", None, "count"),
    "floor_area": (
        # starts only where a number starts, possessive: linear on a long run of digits
        r"(?<![\d,.])(\d[\d,]*+(?:\.\d++)?)"
        r"\s*(sq\.?\s?ft|square feet|sq\.?\s?m\b|m2|m²|square met)",
        None,
        "area",
    ),
    "tenure": (r"Tenure\s*:?\s*(Leasehold|Freehold|Share of Freehold)", None, "str"),
}
# A pasted URL is fetched only on advert sites: never a way to make the server call anything
# (crawl URLs are the organisers' and trusted).
HOSTS = ("auctionhouse.co.uk", "rightmove.co.uk", "zoopla.co.uk", "openrent.co.uk")
MAX_TEXT = 200_000  # characters of an advert's text the patterns read
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "studio": 0}


def _value(raw: str, kind: str):
    if kind == "money":
        return float(raw.replace(",", ""))
    if kind == "area":
        return float(raw.replace(",", ""))
    if kind == "count":
        return int(raw) if raw.isdigit() else WORDS.get(raw.lower())
    return raw.strip()


def parse_advert(text: str) -> dict[str, tuple]:
    """field -> (value, unit, the matched words)."""
    out = {}
    text = text[:MAX_TEXT]
    for field, (pattern, unit, kind) in PATTERNS.items():
        if m := re.search(pattern, text, re.I):
            value = _value(m.group(1), kind)
            if kind == "area":
                unit = "sq ft" if re.search(r"f", m.group(2), re.I) else "m2"
            if value is not None:
                out[field] = (value, unit, m.group(0))
    return out


def advert_site(url: str) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and any(host == h or host.endswith("." + h) for h in HOSTS)


def _page(listing: dict) -> dict:
    if listing["offline"]:
        return listing["fixture"]["page"]
    if "page" in listing:  # pasted text: the advert is the paste
        return listing["page"]
    pasted = not listing["crawl"]
    if pasted and not advert_site(listing["url"]):
        raise SourceOff("not an advert site we read (Rightmove, Zoopla, OpenRent, Auction House)")
    html = get_text(listing["url"], allow=advert_site if pasted else None)
    found = re.findall(r"(?:https://www\.auctionhouse\.co\.uk)?(/lot-image/\d+)", html)
    photos = [urljoin(listing["url"], p) for p in dict.fromkeys(found)]  # gallery order, once
    return {
        "url": listing["url"],
        "fetched_at": now(),
        "text": visible_text(html),
        "photos": photos,
    }


def _crawl_values(row: dict) -> dict[str, tuple]:
    """What the crawl recorded, mapped onto advert fields."""
    out = {}
    basis = (row.get("price_basis") or "").lower()
    if row.get("price_gbp"):
        words = f"price_gbp={row['price_gbp']} ({basis or 'unstated basis'})"
        if basis.startswith("guide"):  # a sale price: same basis as the advert's guide/sold
            out["price"] = (float(row["price_gbp"]), "GBP", words)
        elif basis in ("rent pa", "pa"):
            out["rent_pa"] = (float(row["price_gbp"]), "GBP/year", words)
        # rent psf or unstated: no field to compare it with, so no evidence
    if row.get("status"):
        out["sale_status"] = (row["status"].title(), None, f"status={row['status']}")
    if row.get("tenure"):
        out["tenure"] = (row["tenure"].title(), None, f"tenure={row['tenure']}")
    if row.get("size_sqft"):
        out["floor_area"] = (float(row["size_sqft"]), "sq ft", f"size_sqft={row['size_sqft']}")
    return out


def ingest(place: Place, listing: dict) -> tuple[list[Claim], list[Evidence]]:
    page = _page(listing)
    listing["page"] = page  # later sources and the page read the photos from here
    lid = listing["listing_id"]
    claims = [
        Claim(
            id=f"claim-{lid}-{field}",
            place_id=place.id,
            field=field,
            value=value,
            unit=unit,
            source_url=page["url"],
            doc_span=words,
            captured_at=page["fetched_at"],
        )
        for field, (value, unit, words) in parse_advert(page["text"]).items()
    ]
    row = listing["crawl"]
    evidence = [
        Evidence(
            id=f"ev-crawl-{lid}-{field}",
            place_id=place.id,
            field=field,
            value=value,
            unit=unit,
            source_name=CRAWL,
            source_url=row["url"],
            doc_span=words,
            fetched_at=row.get("crawled_at") or now(),
            agent=NAME,
        )
        for field, (value, unit, words) in _crawl_values(row).items()
    ]
    return claims, evidence
