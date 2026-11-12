"""The one Google Map Tiles fetch per demo listing, saved for every later run (cost rule).

    GOOGLE_MAPS_API_KEY=... uv run python scripts/record_place_imagery.py demo kimberley-road ...

Writes starter/web/static/images/places/<listing_id>/{streetview,satellite,map}.jpg and
places.json. A listing already recorded is skipped, never re-fetched. Runs and page views
serve these files and never call Google. The key stays server side: never printed or saved.
About 5 calls per listing plus 5 shared (sessions, one pano lookup, attribution).
"""

import io
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from starter.verticals.sources import load_listing

OUT = Path(__file__).resolve().parent.parent / "starter/web/static/images/places"
API = "https://tile.googleapis.com/v1"
ACCENT = "#b8ed81"  # tokens.css --color-accent
# A dark roadmap on the page's own palette (tokens.css --color-bg, --color-raised, --color-muted).
DARK = [
    {"elementType": "geometry", "stylers": [{"color": "#141815"}]},
    {"elementType": "labels.text.fill", "stylers": [{"color": "#b4beb2"}]},
    {"elementType": "labels.text.stroke", "stylers": [{"color": "#080a09"}]},
    {"featureType": "road", "elementType": "geometry", "stylers": [{"color": "#2b332c"}]},
    {"featureType": "water", "elementType": "geometry", "stylers": [{"color": "#0b1512"}]},
    {"featureType": "poi", "stylers": [{"visibility": "off"}]},
]
MAX_CALLS = 24
calls = 0


def call(path: str, key: str, params: dict | None = None, body: dict | None = None) -> bytes:
    global calls
    if calls >= MAX_CALLS:
        sys.exit(f"stopped at the {MAX_CALLS}-call cap")
    calls += 1
    url = f"{API}/{path}?" + urllib.parse.urlencode({**(params or {}), "key": key})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as e:  # Google's message only; the URL holds the key
        sys.exit(f"{path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}")


def session(kind: str, key: str, **extra) -> str:
    body = {"mapType": kind, "language": "en-GB", "region": "GB", **extra}
    return json.loads(call("createSession", key, body=body))["session"]


def world(lat: float, lng: float, z: int) -> tuple[float, float]:
    """Web Mercator position in tiles at zoom z."""
    s = math.sin(math.radians(lat))
    n = 2**z
    return (lng + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def heading(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compass bearing from the camera to the property, so Street View faces the front."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360, 1)


def tile(path: Path, sess: str, key: str, lat: float, lng: float, z: int) -> str:
    """One tile with the property ringed; returns the CSS object-position that keeps it in view.
    shortcut: one tile, so the property is off-centre; stitch neighbours if the budget allows."""
    x, y = world(lat, lng, z)
    img = Image.open(io.BytesIO(call(f"2dtiles/{z}/{int(x)}/{int(y)}", key, {"session": sess})))
    img = img.convert("RGB")
    fx, fy = x % 1, y % 1
    px, py, r = fx * img.width, fy * img.height, img.width / 22
    ImageDraw.Draw(img).ellipse(
        (px - r, py - r, px + r, py + r), outline=ACCENT, width=max(3, int(r / 4))
    )
    img.save(path, quality=88)
    return f"{fx * 100:.0f}% {fy * 100:.0f}%"


def attribution(sess: str, key: str, places: list, z: int) -> str:
    lats, lngs = [p.lat for p in places], [p.lng for p in places]
    bounds = {
        "north": max(lats) + 0.01,
        "south": min(lats) - 0.01,
        "east": max(lngs) + 0.01,
        "west": min(lngs) - 0.01,
    }
    try:  # the credit line only; a refused viewport must not lose the images
        got = call("viewport", key, {"session": sess, "zoom": z, **bounds})
        return json.loads(got).get("copyright", "") or "Imagery © Google"
    except SystemExit:
        return "Imagery © Google"


def main(ids: list[str]) -> None:
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or sys.exit("set GOOGLE_MAPS_API_KEY")
    todo = []
    for lid in ids:
        place, listing = load_listing(lid, offline=True)
        folder = OUT / listing["listing_id"]
        if (folder / "places.json").exists():
            print(f"skip {lid}: {folder} already recorded")
        elif place.lat is None or place.lng is None:
            print(f"skip {lid}: no coordinates")
        else:
            todo.append((lid, place, listing["listing_id"], folder))
    if not todo:
        return
    places = [t[1] for t in todo]
    today = date.today().isoformat()
    sv = session("streetview", key)
    found = json.loads(
        call(
            "streetview/panoIds",
            key,
            {"session": sv},
            {"locations": [{"lat": p.lat, "lng": p.lng} for p in places], "radius": 50},
        )
    ).get("panoIds", [])
    sat = session("satellite", key, scale="scaleFactor2x", highDpi=True)
    road = session("roadmap", key, scale="scaleFactor2x", highDpi=True, styles=DARK)
    sat_credit = attribution(sat, key, places, 19) or "Google"
    road_credit = attribution(road, key, places, 16) or "Google"
    for i, (lid, place, listing_id, folder) in enumerate(todo):
        folder.mkdir(parents=True, exist_ok=True)
        lat, lng, centre = place.lat, place.lng, f"{place.lat},{place.lng}"
        tiles = []
        pano = found[i] if i < len(found) else ""
        if pano:
            meta = json.loads(call("streetview/metadata", key, {"session": sv, "panoId": pano}))
            yaw = heading(meta["lat"], meta["lng"], lat, lng)
            thumb = call(
                "streetview/thumbnail",
                key,
                {
                    "session": sv,
                    "panoId": pano,
                    "width": 400,
                    "height": 250,
                    "yaw": yaw,
                    "pitch": 5,
                    "fov": 80,
                },
            )
            Image.open(io.BytesIO(thumb)).convert("RGB").save(folder / "streetview.jpg", quality=90)
            tiles.append(
                {
                    "kind": "streetview",
                    "file": "streetview.jpg",
                    "label": "The front, from the street",
                    "source": "Google Street View",
                    "date": meta.get("date"),
                    "date_note": "captured",
                    "credit": meta.get("copyright") or "© Google",
                    "url": "https://www.google.com/maps/@?api=1&map_action=pano&pano="
                    + urllib.parse.quote(pano),
                }
            )
        else:
            print(f"{lid}: no Street View panorama within 50 m, skipped")
        focus = tile(folder / "satellite.jpg", sat, key, lat, lng, 19)
        tiles.append(
            {
                "kind": "satellite",
                "file": "satellite.jpg",
                "label": "From above",
                "source": "Google satellite",
                "date": today,
                "date_note": "fetched",
                "credit": sat_credit,
                "focus": focus,
                "url": f"https://www.google.com/maps/@?api=1&map_action=map&center={centre}&zoom=19&basemap=satellite",
            }
        )
        focus = tile(folder / "map.jpg", road, key, lat, lng, 16)
        tiles.append(
            {
                "kind": "map",
                "file": "map.jpg",
                "label": "On the map",
                "source": "Google Maps",
                "date": today,
                "date_note": "fetched",
                "credit": road_credit,
                "focus": focus,
                "url": f"https://www.google.com/maps/search/?api=1&query={centre}",
            }
        )
        body = {
            "listing_id": listing_id,
            "address": place.address,
            "attribution": "Imagery © Google",
            "tiles": tiles,
        }
        (folder / "places.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        print(f"{lid}: {folder} ({', '.join(t['kind'] for t in tiles)})")
    print(f"Google Map Tiles calls: {calls}")


if __name__ == "__main__":
    main(sys.argv[1:])
