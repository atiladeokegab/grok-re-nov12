"""Floor plan: the advert's own room schedule ("Living Room - 6.9 x 3.9 ... Total Floor Area -
81 sq.m"), read into a table an analyst can check: each room's area, their sum, and the total the
advert states. One `room_schedule` context finding; the size check itself stays with the EPC.

shortcut: reads the schedule printed in the advert text (metres); reading the floor-plan image
with a vision model is the upgrade for adverts that only publish the drawing.
"""

import re

from starter.core.errors import SourceOff
from starter.core.xray import Evidence, Place, now

NAME = "floor_plan"
ROOM = re.compile(
    r"([A-Z][A-Za-z0-9 ]{1,30}?)\s*[-:–]\s*"
    r"(\d{1,2}(?:\.\d{1,2})?)\s*m?\s*[x×]\s*(\d{1,2}(?:\.\d{1,2})?)\s*m?\b"
)
TOTAL = re.compile(r"Total Floor Area\s*[-:–]?\s*(\d+(?:\.\d+)?)\s*sq\.?\s*m", re.I)


def read_schedule(text: str) -> dict | None:
    """{rooms: [{name, width_m, length_m, area_m2}], rooms_m2, stated_m2, words} or None."""
    found = list(ROOM.finditer(text))
    if len(found) < 2:  # one "3 x 2" is not a schedule
        return None
    rooms = [
        {
            "name": re.sub(r"^Accommodation\s+", "", m[1].strip()),
            "width_m": float(m[2]),
            "length_m": float(m[3]),
            "area_m2": round(float(m[2]) * float(m[3]), 2),
        }
        for m in found
    ]
    total = TOTAL.search(text, found[0].start())
    end = total.end() if total else found[-1].end()
    return {
        "rooms": rooms,
        "rooms_m2": round(sum(r["area_m2"] for r in rooms), 1),
        "stated_m2": float(total.group(1)) if total else None,
        "words": text[found[0].start() : end],
    }


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    page = listing.get("page") or {}
    s = read_schedule(page.get("text", ""))
    if s is None:
        raise SourceOff("the advert prints no room schedule")
    said = (
        f"The floor plan's room schedule lists {len(s['rooms'])} rooms totalling "
        f"{s['rooms_m2']:g} m² (rooms only: no halls, stairs or walls)."
    )
    if s["stated_m2"]:
        said += (
            f" The advert states a total floor area of {s['stated_m2']:g} m²; "
            f"the rooms cover {100 * s['rooms_m2'] / s['stated_m2']:.0f}% of it."
        )
    return [], [
        Evidence(
            id=f"ev-floorplan-{listing['listing_id']}",
            place_id=place.id,
            field="room_schedule",
            value={k: s[k] for k in ("rooms", "rooms_m2", "stated_m2")},
            unit="m2",
            source_name="The advert's floor plan (room schedule)",
            source_url=page.get("url") or listing.get("url"),
            doc_span=said,
            fetched_at=page.get("fetched_at") or now(),
            agent=NAME,
        )
    ]
