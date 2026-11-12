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
import json
import os
import re
from pathlib import Path

from starter.core.errors import NotFound
from starter.core.xray import Place
from starter.verticals.sources import epc, listing_history

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = [listing_history, epc]  # order matters: listing_history fills listing["page"]


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
    if row is None:
        raise NotFound(f"no listing {ref!r} in the crawl or fixtures")
    if offline and fixture is None:
        raise NotFound(f"no offline fixture for {ref!r}")

    def num(v: str) -> float | None:
        return float(v) if v else None

    place = Place(
        id=f"place-{row['listing_id']}",
        address=row["address"],
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
