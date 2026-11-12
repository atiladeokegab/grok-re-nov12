"""Source agents. Each module has NAME and `ingest(place, listing) -> (claims, evidence)` and is
listed in SOURCES; the pipeline runs each as a read-only gateway tool `source_<NAME>`, so every
call is audited. A source with nothing to say returns ([], []) (status "empty"); one that fails
raises (status "error"). Neither ever produces a "matches".

`listing` is the dict built by load_listing: listing_id, url, crawl (the organisers' row),
offline (bool), fixture (dict, offline only), and whatever earlier sources added: `page` (the
advert text and photos) is set by listing_history, which runs first.
"""

import csv
import functools
import hashlib
import json
import os
import re
from pathlib import Path

from starter.core.errors import NotFound
from starter.core.xray import Place, now
from starter.verticals.sources import (
    companies_house,
    epc,
    floor_plan,
    listing_history,
    photo_reuse,
    similar_listings,
    tenant_voices,
)

FIXTURES = Path(__file__).parent / "fixtures"
# order matters: listing_history fills page
SOURCES = [
    listing_history,
    epc,
    companies_house,
    photo_reuse,
    floor_plan,
    tenant_voices,
    similar_listings,
]
LOT = re.compile(
    r"^\s*lot\s+\w+\s*[-:–]?\s*", re.I
)  # an auction's "Lot 8 " / "LOT 12 - " / "Lot 3:"


@functools.cache
def _crawl() -> dict[str, dict]:
    path = os.environ.get("LISTINGS_CSV", "")
    if not path or not Path(path).exists():
        return {}
    with open(path, newline="") as f:
        return {r["listing_id"]: r for r in csv.DictReader(f)}


def load_listing(ref: str, offline: bool = False) -> tuple[Place, dict]:
    """A listing by crawl id, advert URL, or fixture name ('demo'). Offline uses fixtures only."""
    fixture = None
    if re.fullmatch(r"[\w-]{1,80}", ref):  # a name, never a path: URLs only match by lookup
        fixture_path = FIXTURES / f"{ref}.json"
        fixture = json.loads(fixture_path.read_text()) if fixture_path.exists() else None
    if fixture is None:
        for p in FIXTURES.glob("*.json"):
            fx = json.loads(p.read_text())
            if ref in (fx["listing_id"], fx["crawl"]["url"]):
                fixture = fx
    row = (fixture or {}).get("crawl")
    if row is None and not offline:
        rows = _crawl()
        row = rows.get(ref) or next((r for r in rows.values() if r["url"] == ref), None)
    if row is None and offline:
        raise NotFound(f"no listing {ref!r} in the crawl or fixtures")
    if offline and fixture is None:
        raise NotFound(f"no offline fixture for {ref!r}")
    if row is None:
        return pasted(ref)

    def num(v: str) -> float | None:
        return float(v) if v else None

    place = Place(
        id=f"place-{row['listing_id']}",
        address=LOT.sub("", row["address"]),
        postcode=row["postcode"],
        lat=num(row.get("lat", "")),
        lng=num(row.get("lon", "")),
    )
    listing = {
        "listing_id": row["listing_id"],
        "url": row["url"],
        "title": row.get("title", ""),
        "crawl": row,
        "offline": offline,
        "fixture": fixture if offline else None,
    }
    return place, listing


MAX_PASTE = 100_000  # characters kept of a pasted advert; the rest is dropped
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b", re.I)


def pasted(ref: str) -> tuple[Place, dict]:
    """Any other paste: an advert URL (fetched by listing_history) or the advert's own text.
    Never raises: what cannot be read is reported by the run, not refused here."""
    ref = ref.encode("utf-8", "replace").decode().strip()[:MAX_PASTE]  # lone surrogates out
    lid = "paste-" + hashlib.sha256(ref.encode()).hexdigest()[:10]
    is_url = re.fullmatch(r"https?://\S+", ref) is not None
    text = "" if is_url else ref
    pc = POSTCODE.search(text)
    place = Place(id=f"place-{lid}", address="", postcode=pc.group(0).upper() if pc else "")
    url = ref if is_url else f"pasted:{lid}"
    listing = {
        "listing_id": lid,
        "url": url,
        "title": "",
        "crawl": {},
        "offline": False,
        "fixture": None,
    }
    if not is_url:
        listing["page"] = {"url": url, "fetched_at": now(), "text": text, "photos": []}
    return place, listing
