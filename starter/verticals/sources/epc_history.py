"""Dated facts from EPC certificates linked to the exact-address register entry.

Only certificates with an exact displayed address and an assessment or lodgement date
enter the timeline. Valid-until dates are deliberately ignored.
"""

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from starter.core.xray import Evidence, Place
from starter.verticals.sources import epc
from starter.verticals.sources.web import get_text, visible_text

NAME = "epc_history"
SOURCE = "EPC register certificate history"
BASE = epc.BASE
CERTIFICATE_PATH = re.compile(r"/energy-certificate/[A-Za-z0-9-]+")
DATE = r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})"


def _address_key(value: str) -> str:
    value = re.sub(r"^Lot\s+\d+\s+", "", value.strip(), flags=re.I)
    postcode = re.search(epc.POSTCODE, value, re.I)
    address = re.split(epc.POSTCODE, value, maxsplit=1, flags=re.I)[0].casefold()
    words = re.findall(r"[a-z0-9]+", address)
    suffixes = {
        "street",
        "st",
        "road",
        "rd",
        "way",
        "lane",
        "ln",
        "avenue",
        "ave",
        "drive",
        "dr",
        "close",
        "crescent",
        "court",
        "ct",
        "place",
        "square",
        "grove",
        "gardens",
        "terrace",
        "mews",
        "walk",
        "row",
        "parade",
    }
    if suffix := next((index for index, word in enumerate(words) if word in suffixes), None):
        words = words[: suffix + 1]
    code = postcode.group(0).replace(" ", "").upper() if postcode else ""
    return f"{' '.join(words)}|{code}"


def _page_address(text: str) -> str | None:
    if "<" in text:
        element = re.search(
            r"<p\b[^>]*class=[\"'][^\"']*\bepc-address\b[^\"']*[\"'][^>]*>(.*?)</p>",
            text,
            re.I | re.S,
        )
        if element:
            return visible_text(element.group(1)).strip(" ,")
        text = visible_text(text)
    match = re.search(
        r"\bAddress\s*:?[ \t]*(.+?)(?=\s+(?:Energy rating|Energy efficiency|"
        r"Property type|Total floor area)\b)",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip(" ,")
    # The live government page renders its address directly before the rating block.
    match = re.search(rf"^(.+?\b{epc.POSTCODE})\s+Energy rating\b", text, re.I)
    return match.group(1).strip(" ,") if match else None


def match_row(rows: list[str], address: str) -> str | None:
    """Choose a postcode-search certificate only when its full displayed address matches."""
    key = _address_key(address)
    if not key:
        return None
    for row in rows:
        text, separator, path = row.rpartition(" | ")
        if separator and _address_key(text) == key:
            return path
    return None


def _date(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if match := re.search(pattern, text, re.I):
            try:
                return datetime.strptime(match.group(1), "%d %B %Y").date().isoformat()
            except ValueError:
                continue
    return None


def parse_certificate(text: str, url: str, expected_address: str) -> dict | None:
    """Return a dated, identity-checked certificate record, or None if unverified."""
    address = _page_address(text)
    text = visible_text(text)
    address = address or _page_address(text)
    if not address or _address_key(address) != _address_key(expected_address):
        return None
    assessed = _date(text, (rf"Date of assessment\s*:?[ \t]*{DATE}",))
    lodged = _date(
        text,
        (
            rf"Date of lodgement\s*:?[ \t]*{DATE}",
            rf"Date lodged\s*:?[ \t]*{DATE}",
            rf"Date of registration\s*:?[ \t]*{DATE}",
        ),
    )
    certified = _date(text, (rf"Date of certificate\s*:?[ \t]*{DATE}",))
    observed = assessed or lodged or certified
    if not observed:
        return None
    fields = {}
    for field, pattern, value_group in (
        ("energy_rating", r"Energy rating\s+(?:is\s+)?([A-G])\b", 1),
        ("property_type", r"Property type\s+(.+?)\s+Total floor area", 1),
        ("floor_area_m2", r"Total floor area\s+(\d+(?:\.\d+)?)\s+square metres", 1),
    ):
        if match := re.search(pattern, text, re.I):
            raw_value = match.group(value_group)
            value = float(raw_value) if field == "floor_area_m2" else raw_value.strip()
            if field == "energy_rating":
                value = value.upper()
            fields[field] = {"value": value, "quote": match.group(0)}
    return {
        "address": address,
        "assessment_date": assessed,
        "lodgement_date": lodged,
        "certificate_date": certified,
        "observed_at": observed,
        "source_url": url,
        "fields": fields,
    }


class _CertificateLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        if CERTIFICATE_PATH.fullmatch(urlsplit(href).path):
            self.paths.append(href)


def collect_history(documents: list[tuple[str, str]], expected_address: str) -> list[dict]:
    """Parse (URL, raw HTML or text) certificate documents into oldest-first history."""
    records = {}
    for url, text in documents:
        record = parse_certificate(text, url, expected_address)
        if record:
            records[url] = record
    return sorted(records.values(), key=lambda row: (row["observed_at"], row["source_url"]))


def _live_documents(place: Place):
    search_url = f"{BASE}/find-a-certificate/search-by-postcode"
    html = get_text(search_url, {"postcode": place.postcode})
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", html, flags=re.S):
        if href := re.search(r'href="(/energy-certificate/[^\"]+)"', tr):
            rows.append(f"{visible_text(tr)} | {href.group(1)}")
    yield f"{search_url}?postcode={place.postcode.replace(' ', '+')}", html
    current = match_row(rows, place.address)
    if not current:
        return
    current_url = urljoin(BASE, current)
    page = get_text(current_url)
    yield current_url, page
    links = _CertificateLinks()
    links.feed(page)
    seen = {current_url}
    for path in links.paths:
        url = urljoin(BASE, path)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(BASE).netloc:
            continue
        canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if canonical in seen:
            continue
        seen.add(canonical)
        yield canonical, get_text(canonical)


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    if listing["offline"]:
        documents = listing["fixture"].get("epc_history", {}).get("documents", [])
    else:
        documents = _live_documents(place)
    from starter.core.ingest import decoded_text, ground, land

    landed = []
    for url, raw in documents:
        document = land(
            listing,
            raw=raw,
            source_url=url,
            agent=NAME,
            content_type="text/html",
        )
        landed.append((url, raw, document))
    history = collect_history([(url, raw) for url, raw, _ in landed], place.address)
    if not history:
        return [], []
    document_by_url = {url: doc for url, _, doc in landed}
    evidence = []
    for certificate in history:
        document = document_by_url[certificate["source_url"]]
        text = decoded_text(document)
        if text is None:
            continue
        for field, data in certificate["fields"].items():
            span = ground(text, data["quote"])
            if not span:
                continue
            evidence.append(
                Evidence(
                    id=(
                        f"ev-epc-history-{listing['listing_id']}-"
                        f"{certificate['source_url'].rsplit('/', 1)[-1]}-{field}"
                    ),
                    place_id=place.id,
                    field=field,
                    value=data["value"],
                    unit="m2" if field == "floor_area_m2" else None,
                    source_name=SOURCE,
                    source_url=certificate["source_url"],
                    doc_span=span.quote,
                    fetched_at=document.fetched_at,
                    agent=NAME,
                    document_id=document.id,
                    span=span,
                    observed_at=certificate["observed_at"],
                )
            )
    return [], evidence
