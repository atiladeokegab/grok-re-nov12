"""Compare actual perceptual hashes across dated adverts, independent of photo order."""

import re
from datetime import datetime
from io import BytesIO
from itertools import pairwise
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from starter.core.xray import Claim, Evidence, Place

NAME = "photo_diff"
FIXTURE = {"adverts": []}
HASH = re.compile(r"[0-9a-fA-F]{16}\Z")


def perceptual_hash(content: bytes) -> str:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        pixels = list(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{value:016x}"


def _photos(advert: dict) -> list[dict]:
    photos = advert.get("photos", [])
    if not photos or any(
        not isinstance(photo, dict)
        or not HASH.fullmatch(str(photo.get("phash", "")))
        or photo.get("hash_algorithm", "dhash64") != "dhash64"
        or not _web_url(photo.get("url"))
        for photo in photos
    ):
        return []
    return photos


def _web_url(url: str | None) -> bool:
    try:
        parts = urlsplit(url or "")
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


def compare_adverts(adverts: list[dict]) -> list[dict]:
    dated = []
    for advert in adverts:
        stamp = advert.get("captured_at") or advert.get("fetched_at")
        if not stamp or not advert.get("advert_id"):
            continue
        try:
            captured = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if captured.tzinfo is None:
            continue
        dated.append((captured, advert))
    dated.sort(key=lambda item: item[0])
    changes = []
    for (before_time, before), (after_time, after) in pairwise(dated):
        if before_time == after_time:
            continue
        old, new = _photos(before), _photos(after)
        if not old or not new:
            continue

        def unmatched(first, second):
            # shortcut: dHash detects structural change, not image ownership or digital staging.
            return [
                p["url"]
                for p in first
                if not any(
                    (int(p["phash"], 16) ^ int(q["phash"], 16)).bit_count() <= 6 for q in second
                )
            ]

        added, removed = unmatched(new, old), unmatched(old, new)
        if added or removed:
            changes.append(
                {
                    "previous_advert_id": before["advert_id"],
                    "advert_id": after["advert_id"],
                    "previous_captured_at": before_time.isoformat(),
                    "captured_at": after_time.isoformat(),
                    "added": added,
                    "removed": removed,
                    "source_url": after.get("source_url") or after.get("url"),
                    "interpretation": "Photo set changed; reason for the change is unverified",
                }
            )
    return changes


def ingest(place: "Place", listing: dict) -> tuple[list["Claim"], list["Evidence"]]:
    from starter.core.xray import Evidence

    fixture = (listing.get("fixture") or {}).get(NAME) if listing.get("offline") else None
    adverts = (fixture if fixture is not None else listing).get("adverts", [])
    evidence = []
    for index, change in enumerate(compare_adverts(adverts)):
        url = change["source_url"]
        if not _web_url(url):
            continue
        evidence.append(
            Evidence(
                id=f"{place.id}:{NAME}:{index}",
                place_id=place.id,
                field="photo_history",
                value=change,
                source_name="Listing photo history",
                source_url=url,
                fetched_at=change["captured_at"],
                agent=NAME,
            )
        )
    return [], evidence
