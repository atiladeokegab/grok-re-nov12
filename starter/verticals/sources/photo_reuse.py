"""Photo reuse: this advert's photos, hashed (sha256 of the image bytes), against the photos of
the crawl's other adverts for the same address (a relisting). A byte-identical photo on another
advert is a `photo_reuse` flag citing that advert; no other advert, or none shared, is "empty".

shortcut: candidates are only the crawl's rows with the same address; a cross-address search
(perceptual hash over the whole crawl) is the upgrade when there is an index to search.
"""

import hashlib
import re

from starter.core.errors import SourceOff
from starter.core.xray import Evidence, Place, now
from starter.verticals.sources.web import get_bytes, get_text

NAME = "photo_reuse"
LOT = re.compile(r"^(?:Lot \w+\s+|Property for Auction in [^-]+- )", re.I)


def _addr(address: str) -> str:
    return LOT.sub("", address).strip().lower()


def _hashes(urls: list[str]) -> dict[str, str]:
    return {u: hashlib.sha256(get_bytes(u)).hexdigest() for u in urls}


def _photos(url: str) -> list[str]:
    found = re.findall(r"(?:https://www\.auctionhouse\.co\.uk)?(/lot-image/\d+)", get_text(url))
    return [f"https://www.auctionhouse.co.uk{p}" for p in dict.fromkeys(found)]


def capture(listing: dict) -> dict:
    """{fetched_at, photos: {url: sha256}, others: [{listing_id, url, crawl, photos}]}."""
    from starter.verticals.sources import _crawl  # late: the package imports this module

    row = listing["crawl"]
    others = [
        r
        for r in _crawl().values()
        if r["listing_id"] != row["listing_id"] and _addr(r["address"]) == _addr(row["address"])
    ]
    return {
        "fetched_at": now(),
        "photos": _hashes(listing.get("page", {}).get("photos", [])) if others else {},
        "others": [
            {
                "listing_id": r["listing_id"],
                "url": r["url"],
                "crawl": {k: r[k] for k in ("status", "price_gbp", "listed_or_auction_date")},
                "photos": _hashes(_photos(r["url"])),
            }
            for r in others
        ],
    }


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    if not listing["crawl"]:  # a pasted advert
        raise SourceOff("not in the crawl: no other adverts to compare photos with")
    if listing["offline"]:
        data = (listing["fixture"] or {}).get("photo_reuse")
        if data is None:
            raise SourceOff("offline, and this fixture recorded no photo hashes")
    else:
        data = capture(listing)
    mine = set(data["photos"].values())
    evidence = []
    for o in data["others"]:
        shared = [u for u, h in o["photos"].items() if h in mine]
        if not shared:
            continue
        c = o["crawl"]
        said = (
            f"{len(shared)} of {len(mine)} photos are byte-identical (sha256) to {o['url']}, "
            f"which the crawl recorded as {c['status']} at £{float(c['price_gbp'] or 0):,.0f} "
            f"({c['listed_or_auction_date'] or 'undated'})."
        )
        evidence.append(
            Evidence(
                id=f"ev-photo-{listing['listing_id']}-{o['listing_id']}",
                place_id=place.id,
                field="photo_reuse",
                value=len(shared),
                source_name="Organisers' listings crawl (other advert)",
                source_url=o["url"],
                doc_span=said,
                fetched_at=data["fetched_at"],
                agent=NAME,
            )
        )
    return [], evidence
