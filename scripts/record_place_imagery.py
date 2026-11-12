"""The one Google Maps fetch per demo listing, saved for every later run (cost rule).

    GOOGLE_MAPS_API_KEY=... uv run python scripts/record_place_imagery.py demo kimberley-road ...

Writes starter/web/static/images/places/<listing_id>/{streetview,satellite,map}.jpg and
places.json. A listing already recorded is skipped, never re-fetched. Runs and page views
serve these files and never call Google. The key stays server side: it is never printed or saved.
"""

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from starter.verticals.sources import load_listing

OUT = Path(__file__).resolve().parent.parent / "starter/web/static/images/places"
API = "https://maps.googleapis.com/maps/api"
# A dark roadmap on the page's own palette (tokens.css --color-bg, --color-raised, --color-accent).
DARK = [
    "element:geometry|color:0x141815",
    "element:labels.text.fill|color:0xb4beb2",
    "element:labels.text.stroke|color:0x080a09",
    "feature:road|element:geometry|color:0x2b332c",
    "feature:water|element:geometry|color:0x0b1512",
    "feature:poi|visibility:off",
    "feature:transit|visibility:simplified",
]
calls = {"billed": 0, "free": 0}


def get(path: str, params: dict, key: str, billed: bool = True) -> bytes:
    calls["billed" if billed else "free"] += 1
    query = urllib.parse.urlencode({**params, "key": key}, doseq=True)
    with urllib.request.urlopen(f"{API}/{path}?{query}", timeout=30) as response:
        return response.read()


def heading(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compass bearing from the camera to the property, so Street View faces the front."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360, 1)


def record(lid: str, key: str) -> Path:
    place, listing = load_listing(lid, offline=True)
    folder = OUT / listing["listing_id"]
    if (folder / "places.json").exists():
        raise FileExistsError(f"{folder} already recorded")
    lat, lng = place.lat, place.lng
    if lat is None or lng is None:
        raise ValueError("no coordinates")
    folder.mkdir(parents=True, exist_ok=True)
    centre = f"{lat},{lng}"
    today = date.today().isoformat()
    tiles = []

    meta = json.loads(
        get(
            "streetview/metadata",
            {"location": centre, "source": "outdoor", "radius": 60},
            key,
            billed=False,
        )
    )
    if meta.get("status") == "OK":
        loc = meta["location"]
        (folder / "streetview.jpg").write_bytes(
            get(
                "streetview",
                {
                    "pano": meta["pano_id"],
                    "size": "640x400",
                    "fov": 80,
                    "pitch": 5,
                    "heading": heading(loc["lat"], loc["lng"], lat, lng),
                    "return_error_code": "true",
                },
                key,
            )
        )
        tiles.append(
            {
                "kind": "streetview",
                "file": "streetview.jpg",
                "label": "The front, from the street",
                "source": "Google Street View",
                "date": meta.get("date"),
                "date_note": "captured",
                "url": "https://www.google.com/maps/@?api=1&map_action=pano&pano="
                + urllib.parse.quote(meta["pano_id"]),
            }
        )
    else:
        print(f"{lid}: no Street View imagery ({meta.get('status')})")

    (folder / "satellite.jpg").write_bytes(
        get(
            "staticmap",
            {
                "center": centre,
                "zoom": 19,
                "size": "640x400",
                "scale": 2,
                "maptype": "satellite",
                "format": "jpg",
            },
            key,
        )
    )
    tiles.append(
        {
            "kind": "satellite",
            "file": "satellite.jpg",
            "label": "From above",
            "source": "Google satellite",
            "date": today,
            "date_note": "fetched",
            "url": f"https://www.google.com/maps/@?api=1&map_action=map&center={centre}&zoom=19&basemap=satellite",
        }
    )
    (folder / "map.jpg").write_bytes(
        get(
            "staticmap",
            {
                "center": centre,
                "zoom": 16,
                "size": "640x400",
                "scale": 2,
                "format": "jpg",
                "style": DARK,
                "markers": f"color:0xb8ed81|{centre}",
            },
            key,
        )
    )
    tiles.append(
        {
            "kind": "map",
            "file": "map.jpg",
            "label": "On the map",
            "source": "Google Maps",
            "date": today,
            "date_note": "fetched",
            "url": f"https://www.google.com/maps/search/?api=1&query={centre}",
        }
    )
    body = {
        "listing_id": listing["listing_id"],
        "address": place.address,
        "attribution": "Imagery © Google",
        "tiles": tiles,
    }
    (folder / "places.json").write_text(json.dumps(body, indent=2) + "\n")
    return folder


def main(ids: list[str]) -> None:
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or sys.exit("set GOOGLE_MAPS_API_KEY")
    for lid in ids:
        try:
            print(f"{lid}: {record(lid, key)}")
        except (FileExistsError, ValueError) as e:
            print(f"skip {lid}: {e}")
    print(f"Google calls: {calls['billed']} billed, {calls['free']} free metadata")


if __name__ == "__main__":
    main(sys.argv[1:])
