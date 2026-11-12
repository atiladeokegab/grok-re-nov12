"""EPC register (find-energy-certificate.service.gov.uk, public, Open Government Licence): the
certificate for this address gives energy rating, property type and floor area, each cited to
the certificate's own URL. No certificate for the address means no evidence (status "empty"),
so the reconciler marks the advert's rating unverifiable, never matched.
"""

import re

from starter.core.xray import Evidence, Place, now
from starter.verticals.sources.web import get_text, visible_text

NAME = "epc"
SOURCE = "EPC register"
BASE = "https://find-energy-certificate.service.gov.uk"


def _key(address: str) -> tuple[str, str]:
    """(house or flat number, first street word): enough to pick one row in a postcode."""
    a = re.sub(r"^Lot \d+\s+", "", address, flags=re.I)
    flat = re.search(r"\b(?:Flat|Apartment|Unit)\s+(\w+)", a, re.I)
    number = flat.group(1) if flat else (re.search(r"\b(\d+[A-Z]?)\b", a) or [None, ""])[1]
    street = re.search(r"\d+[A-Z]?,?\s+([A-Za-z]+)", a)
    return number.lower(), (street.group(1).lower() if street else "")


def match_row(rows: list[str], address: str) -> str | None:
    """The certificate path of the row for this address, or None. Rows are 'address ... | path'."""
    number, street = _key(address)
    for row in rows:
        text, _, path = row.rpartition(" | ")
        row_number, row_street = _key(text)
        if row_number == number and street and street in text.lower():
            return path
    return None


def parse_certificate(text: str) -> dict:
    out = {}
    if m := re.search(r"energy rating is ([A-G])\b", text):
        out["energy_rating"] = (m.group(1), None, m.group(0))
    if m := re.search(r"Property type (.+?) Total floor area", text):
        out["property_type"] = (m.group(1).strip(), None, m.group(0))
    if m := re.search(r"Total floor area (\d+(?:\.\d+)?) square metres", text):
        out["floor_area"] = (float(m.group(1)), "m2", m.group(0))
    if m := re.search(r"Valid until (\d{1,2} \w+ \d{4})", text):
        out["epc_valid_until"] = (m.group(1), None, m.group(0))
    return out


def _search(place: Place, listing: dict) -> tuple[str, list[str], dict[str, str], str]:
    if listing["offline"]:
        fx = listing["fixture"]["epc"]
        return fx["search_url"], fx["rows"], fx["certificates"], fx["fetched_at"]
    url = f"{BASE}/find-a-certificate/search-by-postcode"
    html = get_text(url, {"postcode": place.postcode})
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", html, flags=re.S):
        if href := re.search(r'href="(/energy-certificate/[^"]+)"', tr):
            rows.append(f"{visible_text(tr)} | {href.group(1)}")
    path = match_row(rows, place.address)
    certs = {path: visible_text(get_text(BASE + path))} if path else {}
    return f"{url}?postcode={place.postcode.replace(' ', '+')}", rows, certs, now()


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    _, rows, certs, fetched_at = _search(place, listing)
    path = match_row(rows, place.address)
    if not path or path not in certs:
        return [], []
    return [], [
        Evidence(
            id=f"ev-epc-{listing['listing_id']}-{field}",
            place_id=place.id,
            field=field,
            value=value,
            unit=unit,
            source_name=SOURCE,
            source_url=BASE + path,
            doc_span=words,
            fetched_at=fetched_at,
            agent=NAME,
        )
        for field, (value, unit, words) in parse_certificate(certs[path]).items()
    ]
