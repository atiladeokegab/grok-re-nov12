"""Similar listings: the five most comparable listings in the organisers' crawl, for an analyst's
comparables table. Same postcode district first (then the same postcode area), same property
type and price basis, same bedrooms where the advert says, nearest price. Offline: reads the local
crawl (LISTINGS_CSV, else the gitignored SLICE that deploy uploads) once and keeps a small index in
memory. One `comparables` context finding. A price is called above or below the median only
against at least MIN_LIKE comparables in the same postcode district.

Make the slice before a deploy (only the columns and rows this source uses):
    uv run python -m starter.verticals.sources.similar_listings <organisers' listings.csv>

shortcut: bedrooms come from the crawl's price text and title ("3 Bedroom"), which most rows lack;
the advert pages are the upgrade when a firm needs bed-for-bed comparables.
"""

import csv
import functools
import math
import os
import re
import statistics
import sys
from pathlib import Path

from starter.core.errors import SourceOff
from starter.core.xray import Evidence, Place, now

NAME = "similar_listings"
TOP = 5
MIN_LIKE = 3  # same-district comparables needed before a price is compared
SLICE = Path(__file__).parent / "comparables.csv"  # gitignored; .gcloudignore uploads it
COLUMNS = "listing_id url title address postcode property_type sale_or_let price_gbp price_basis"
COLUMNS = [*COLUMNS.split(), "price_text", "size_sqft", "lat", "lon"]
SQFT_M2 = 0.09290304
MIN_SALE = 10_000  # shortcut: lower "guide" prices in the crawl are fees or ground rents
BEDS = re.compile(r"(\d{1,2})\s*-?\s*bed(?:room)?s?\b", re.I)
PCM = re.compile(r"per calendar month|\bpcm\b|per month", re.I)
TYPES = {
    "flat": "flat",
    "apartment": "flat",
    "residential flat / block": "flat",
    "maisonette": "flat",
    "house": "house",
    "cottage": "house",
    "bungalow": "house",
    "residential house": "house",
}
BASIS_WORDS = {"sale": "guide", "pcm": "pcm", "pa": "pa", "psf": "psf"}


def _num(v: str) -> float | None:
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _row(r: dict) -> dict:
    """A crawl row reduced to what comparing needs."""
    text = f"{r.get('price_text', '')} {r.get('title', '')}"
    beds = BEDS.search(text)
    basis = (
        "pcm"
        if PCM.search(r.get("price_text", ""))
        else "psf"
        if "psf" in r.get("price_basis", "")
        else "pa"
        if r.get("sale_or_let") == "let" or "pa" in r.get("price_basis", "").split()
        else "sale"
    )
    price = _num(r.get("price_gbp", ""))
    if price is not None and (price <= 0 or (basis == "sale" and price < MIN_SALE)):
        price = None
    pc = (r.get("postcode") or "").upper().split()
    kind = (r.get("property_type") or "").strip().lower()
    address = re.sub(r"^\s*lot\s+\w+\s*[-:–]?\s*", "", r.get("address", ""), flags=re.I)
    if "+44" in address:  # some agents' rows hold the office's contact line, not the address
        address = r.get("title", "")
    return {
        "listing_id": r["listing_id"],
        "url": r.get("url", ""),
        "address": address,
        "district": pc[0] if pc else "",
        "area": re.match(r"[A-Z]*", pc[0]).group(0) if pc else "",
        "type": TYPES.get(kind, kind),
        "beds": int(beds[1]) if beds else (0 if re.search(r"\bstudio\b", text, re.I) else None),
        "basis": basis,
        "price": price,
        "size_m2": (_num(r.get("size_sqft", "")) or 0) * SQFT_M2 or None,
        "lat": _num(r.get("lat", "")),
        "lng": _num(r.get("lon", "")),
    }


@functools.cache
def _index() -> dict[str, list[dict]]:
    """Comparable rows by postcode area, built once from the local crawl."""
    path = Path(os.environ.get("LISTINGS_CSV") or SLICE)
    if not path.is_file():
        return {}
    out: dict[str, list[dict]] = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            row = _row(r)
            if _usable(row):
                out.setdefault(row["area"], []).append(row)
    return out


def _usable(row: dict) -> bool:
    return bool(row["area"] and row["price"] and row["type"])


def _km(a: dict, b: dict) -> float:
    if None in (a["lat"], a["lng"], b["lat"], b["lng"]):
        return math.inf
    x = math.radians(b["lng"] - a["lng"]) * math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    return 6371 * math.hypot(x, math.radians(b["lat"] - a["lat"]))


def find(me: dict, index: dict[str, list[dict]]) -> list[dict]:
    def key(c: dict) -> tuple:
        beds = 1 if None in (me["beds"], c["beds"]) else 2 * (me["beds"] != c["beds"])
        price = abs(math.log(c["price"] / me["price"])) if me["price"] else 0
        if c["district"] == me["district"]:
            return (0, beds, price)
        return (1, beds, _km(me, c), price)  # outside the district: nearest first

    pool = [
        c
        for c in index.get(me["area"], [])
        if c["type"] == me["type"]
        and c["basis"] == me["basis"]
        and c["listing_id"] != me["listing_id"]
    ]
    seen, out = {me["address"].lower()}, []
    for c in sorted(pool, key=key):  # a relisted property counts once, at its closest price
        if c["address"].lower() not in seen and len(out) < TOP:
            seen.add(c["address"].lower())
            out.append(c)
    return out


def _kinds(kind: str, n: int) -> str:
    return kind if n == 1 or kind.endswith("s") else f"{kind}s"


def _gbp(v: float, basis: str) -> str:
    return f"£{v:,.0f}" + ("" if basis == "sale" else f" {BASIS_WORDS[basis]}")


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    if not listing.get("crawl"):
        raise SourceOff("a pasted advert has no crawl row to compare")
    index = _index()
    if not index:
        raise SourceOff("no local crawl to compare against (LISTINGS_CSV or SLICE)")
    me = _row(listing["crawl"])
    comps = find(me, index)
    if not comps:
        raise SourceOff(f"no comparable {me['type'] or 'listing'} in {me['area'] or 'its area'}")

    local = [c for c in comps if c["district"] == me["district"]]
    beds = (
        f"{me['beds']}-bed " if me["beds"] and all(c["beds"] == me["beds"] for c in local) else ""
    )
    raw = _num(listing["crawl"].get("price_gbp", ""))
    if len(local) >= MIN_LIKE:
        prices = [c["price"] for c in local]
        said = (
            f"{len(local)} similar {beds}{_kinds(me['type'], len(local))} in {me['district']} "
            f"list at {_gbp(min(prices), 'sale')}–{_gbp(max(prices), me['basis'])}"
        )
        if me["price"]:
            median = statistics.median(prices)
            side = "above" if me["price"] > median else "below" if me["price"] < median else "at"
            said += (
                f"; this one asks {_gbp(me['price'], me['basis'])}, {side} the median of "
                f"{_gbp(median, me['basis'])}"
            )
        said += "."
    else:
        n = len(local)
        said = (
            f"No other similar {me['type']} in {me['district']} is in the crawl"
            if n == 0
            else f"Only {n} other similar {_kinds(me['type'], n)} in {me['district']} "
            f"{'is' if n == 1 else 'are'} in the crawl"
        )
        away = list(dict.fromkeys(c["district"] for c in comps if c not in local))
        if away:
            joined = ", ".join(away[:-1]) + " and " + away[-1] if len(away) > 1 else away[0]
            said += f"; the nearest {'others ' if n else ''}are in {joined}"
        said += ", so this is not a like-for-like price comparison."
    if not me["price"]:  # never compared: a fee is not a guide price
        said += (
            f" The crawl's price for this one ({_gbp(raw, 'sale')}) is too low to be a guide "
            "price (likely a fee), so it is not compared."
            if raw
            else " The crawl records no price for this one, so it is not compared."
        )

    value = [
        {
            "address": c["address"],
            "price": c["price"],
            "beds": c["beds"],
            "type": c["type"],
            "url": c["url"],
            "listing_id": c["listing_id"],
        }
        | ({"price_per_m2": round(c["price"] / c["size_m2"])} if c["size_m2"] else {})
        for c in comps
    ]
    return [], [
        Evidence(
            id=f"ev-similar-{listing['listing_id']}",
            place_id=place.id,
            field="comparables",
            value=value,
            unit="GBP",
            source_name="Organisers' listings crawl (comparable listings)",
            # a fragment, so the run never "grounds" this sentence in the advert's crawl row
            source_url=f"{listing.get('url')}#comparables",
            doc_span=said,
            fetched_at=listing["crawl"].get("crawled_at") or now(),
            agent=NAME,
        )
    ]


if __name__ == "__main__":  # write SLICE from the organisers' full crawl CSV
    with open(sys.argv[1], newline="") as src, open(SLICE, "w", newline="") as out:
        w = csv.DictWriter(out, COLUMNS, extrasaction="ignore")
        w.writeheader()
        rows = [r for r in csv.DictReader(src) if _usable(_row(r))]
        w.writerows(rows)
    print(f"{SLICE}: {len(rows)} rows")
