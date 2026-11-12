"""Exact-address transaction history from HM Land Registry's Price Paid Data."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx

from starter.verticals.sources.web import UA

NAME = "hmlr_history"
SOURCE = "HM Land Registry Price Paid Data"
API_URL = "https://landregistry.data.gov.uk/data/ppi/transaction-record.json"
TIMEOUT = 12
PAGE_SIZE = 100
MAX_PAGES = 10
ATTRIBUTION = (
    "Contains HM Land Registry data © Crown copyright and database right 2021. "
    "This data is licensed under the Open Government Licence v3.0."
)
_STREET_SUFFIX = re.compile(
    r"\b(?:road|rd|street|st|way|avenue|ave|lane|ln|close|crescent|court|drive|"
    r"gardens|grove|place|square|terrace|walk|mews|rise|row|park|parade)\b",
    re.I,
)


def _norm(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _target(address: str) -> tuple[str, str, str] | None:
    """Extract PAON, SAON and street; discard only trailing locality components.

    Ambiguous/nonconventional addresses abstain. A listing without an explicit unit
    only matches PPD rows whose SAON is also empty.
    """
    value = re.sub(r"^Lot\s+\d+\s+", "", re.sub(r"\s+", " ", address.strip()), flags=re.I)
    value = re.sub(r"\s+[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", "", value, flags=re.I)
    saon = ""
    unit = re.match(r"^(flat|apartment|unit)\s+([^,]+?)(?:,\s*|\s+)(.+)$", value, re.I)
    if unit:
        saon = f"{unit.group(1)} {unit.group(2)}"
        value = unit.group(3).strip()

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) >= 2:
        first = parts[0]
        # Numeric PAON and street commonly share one field; locality follows commas.
        numbered = re.match(r"^(\d+[A-Z]?(?:-\d+[A-Z]?)?)\s+(.+)$", first, re.I)
        if numbered:
            paon, street = numbered.group(1), numbered.group(2)
        elif re.fullmatch(r"\d+[A-Z]?(?:-\d+[A-Z]?)?", first, re.I):
            paon, street = first, parts[1]
        elif _STREET_SUFFIX.search(parts[1]):
            # Comma-delimited building name, then a recognizable street name.
            paon, street = first, parts[1]
        else:
            return None
    else:
        match = re.match(r"^(\d+[A-Z]?(?:-\d+[A-Z]?)?)\s+(.+)$", value, re.I)
        if not match:
            return None
        paon, street = match.group(1), match.group(2)
    if not paon or not street or not _STREET_SUFFIX.search(street):
        return None
    return paon, saon, street


def _scalar(value: Any) -> str:
    if isinstance(value, dict):
        if "_value" in value:
            return str(value["_value"]).strip()
        if "_about" in value:
            return str(value["_about"]).strip()
        labels = value.get("label") or value.get("prefLabel") or []
        if labels and isinstance(labels[0], dict):
            return str(labels[0].get("_value", "")).strip()
    return "" if value is None else str(value).strip()


def _address(record: dict) -> dict[str, str]:
    addr = record.get("propertyAddress") or record.get("property_address") or {}
    if not isinstance(addr, dict):
        return {key: "" for key in ("paon", "saon", "street", "postcode")}
    return {key: _scalar(addr.get(key)) for key in ("paon", "saon", "street", "postcode")}


def exact_address_match(record: dict, address: str, postcode: str) -> bool:
    target = _target(address)
    if not target or not postcode.strip():
        return False
    row = _address(record)
    paon, saon, street = target
    return (
        _norm(row["paon"]) == _norm(paon)
        and _norm(row["saon"]) == _norm(saon)
        and _norm(row["street"]) == _norm(street)
        and _norm(row["postcode"]) == _norm(postcode)
    )


def _items(payload: dict) -> list[dict] | None:
    """Support HMLR's actual Linked Data API ``result.items`` response."""
    if "result" in payload:
        result = payload["result"]
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            return result["items"]
        return None
    if "_embedded" in payload:
        embedded = payload["_embedded"]
        if isinstance(embedded, dict) and isinstance(embedded.get("item"), list):
            return embedded["item"]
    return None


def _date(value: Any) -> str | None:
    raw = _scalar(value)
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        try:
            return datetime.strptime(raw, "%a, %d %b %Y").date().isoformat()
        except (TypeError, ValueError, OverflowError):
            try:
                return parsedate_to_datetime(raw).date().isoformat()
            except (TypeError, ValueError, OverflowError):
                return None


def _price(value: Any) -> int | None:
    try:
        amount = Decimal(_scalar(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        return None
    return int(amount)


def _label_code(value: Any) -> str:
    return _scalar(value).casefold().replace("_", "-").rsplit("/", 1)[-1]


def _property_type(value: Any) -> str | None:
    return {
        "detached": "Detached",
        "semi-detached": "Semi-detached",
        "terraced": "Terraced",
        "flat-maisonette": "Flat/maisonette",
        "other": "Other",
        "d": "Detached",
        "s": "Semi-detached",
        "t": "Terraced",
        "f": "Flat/maisonette",
        "o": "Other",
    }.get(_label_code(value))


def _tenure(value: Any) -> str | None:
    return {
        "freehold": "Freehold",
        "leasehold": "Leasehold",
        "f": "Freehold",
        "l": "Leasehold",
    }.get(_label_code(value))


def _source_url(value: Any) -> str | None:
    try:
        parts = urlsplit(_scalar(value))
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or parts.hostname != "landregistry.data.gov.uk"
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or not parts.path.startswith("/data/ppi/transaction/")
    ):
        return None
    return f"https://landregistry.data.gov.uk{parts.path}"


def parse_transactions(payload: dict, address: str, postcode: str) -> list[dict]:
    """Return only dated sales whose complete address including unit matches exactly."""
    out = []
    rows = _items(payload)
    if not isinstance(rows, list):
        return []
    for row in rows[: PAGE_SIZE * MAX_PAGES]:
        if not isinstance(row, dict) or not exact_address_match(row, address, postcode):
            continue
        price = _price(row.get("pricePaid"))
        trans_date = _date(row.get("transactionDate"))
        if price is None or trans_date is None:
            continue
        uri = _source_url(row.get("_about"))
        if uri is None:
            continue
        transaction_id = _scalar(row.get("transactionId"))
        if not transaction_id and uri:
            transaction_id = uri.rstrip("/").split("/")[-2]
        if not transaction_id:
            continue
        out.append(
            {
                "transaction_id": transaction_id,
                "transaction_uri": _scalar(row.get("_about")),
                "transaction_date": trans_date,
                "price": price,
                "currency": "GBP",
                "price_basis": "achieved sale price",
                "tenure": _tenure(row.get("estateType")),
                "property_type": _property_type(row.get("propertyType")),
                "source_name": SOURCE,
                "source_url": uri,
                "address": _address(row),
            }
        )
    return sorted(out, key=lambda row: (row["transaction_date"], row["transaction_id"]))


def _item_quotes(text: str) -> dict[str, str]:
    """Extract exact original JSON spans keyed by transaction URI/ID."""
    match = re.search(r'"items"\s*:\s*\[', text)
    if not match:
        return {}
    decoder = json.JSONDecoder()
    cursor = match.end()
    quotes = {}
    while cursor < len(text):
        while cursor < len(text) and (text[cursor].isspace() or text[cursor] == ","):
            cursor += 1
        if cursor >= len(text) or text[cursor] == "]":
            break
        start = cursor
        try:
            row, cursor = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            break
        if not isinstance(row, dict):
            continue
        for key in (_scalar(row.get("_about")), _scalar(row.get("transactionId"))):
            if key:
                quotes[key] = text[start:cursor]
    return quotes


def parse_documents(documents: list[dict], address: str, postcode: str) -> list[dict]:
    """Parse paginated API docs and attach exact JSON quotes for core.ground()."""
    by_id = {}
    for document in documents:
        payload = document.get("payload")
        content = document.get("content", b"")
        text = (
            content.decode("utf-8", errors="replace")
            if isinstance(content, bytes)
            else str(content)
        )
        quotes = _item_quotes(text)
        if isinstance(payload, dict):
            for row in parse_transactions(payload, address, postcode):
                row["doc_quote"] = quotes.get(row.get("transaction_uri")) or quotes.get(
                    row["transaction_id"]
                )
                row["document_url"] = document.get("url")
                by_id[row["transaction_id"]] = row
    return sorted(by_id.values(), key=lambda row: (row["transaction_date"], row["transaction_id"]))


def collect(address: str, postcode: str) -> tuple[list[dict], str]:
    """Fetch a bounded number of postcode pages; cap overflow is an explicit error."""
    if not _target(address) or not postcode.strip():
        raise ValueError("A parseable full address and postcode are required")
    params = {"propertyAddress.postcode": postcode.strip(), "_pageSize": PAGE_SIZE}
    pages = []
    last_url = API_URL
    for page in range(1, MAX_PAGES + 1):
        response = httpx.get(
            API_URL,
            params={**params, "_page": page},
            headers=UA,
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("HM Land Registry returned an unexpected response")
        rows = _items(payload)
        if rows is None:
            raise ValueError("HM Land Registry returned an unexpected item list")
        last_url = str(response.url)
        pages.append({"url": last_url, "content": response.content, "payload": payload})
        if len(rows) < PAGE_SIZE:
            break
        if page == MAX_PAGES:
            raise RuntimeError("HM Land Registry result limit reached; history may be incomplete")
    return pages, last_url


def ingest(place, listing: dict) -> tuple[list, list]:
    """Land each original JSON page and emit dated scalar evidence with verified spans."""
    if listing.get("offline"):
        documents = listing.get("fixture", {}).get("hmlr_history", {}).get("documents", [])
    else:
        documents, _ = collect(place.address, place.postcode)
    if not documents:
        return [], []

    # Lazy import keeps pure parsing usable while Hermes' core module is being integrated.
    from starter.core.ingest import decoded_text, ground, land
    from starter.core.xray import Evidence, now

    docs = []
    for item in documents:
        raw = item["content"]
        document = land(
            listing,
            raw=raw,
            source_url=item["url"],
            agent=NAME,
            content_type="application/json",
            fetched_at=now(),
        )
        docs.append((item, document))

    evidence = []
    by_page = {item.get("url"): document for item, document in docs}
    records = parse_documents(documents, place.address, place.postcode)
    for record in records:
        source_page = by_page.get(record.get("document_url"))
        if not source_page:
            continue
        document = source_page
        quote = record.get("doc_quote")
        document_text = decoded_text(document)
        span = ground(document_text, quote) if quote and document_text else None
        if span is None:
            continue
        for field, value, unit in (
            ("sale_price_gbp", record["price"], "GBP"),
            ("tenure", record["tenure"], None),
            ("property_type", record["property_type"], None),
        ):
            if value is None:
                continue
            evidence.append(
                Evidence(
                    id=f"ev-hmlr-{listing['listing_id']}-{record['transaction_id']}-{field}",
                    place_id=place.id,
                    field=field,
                    value=value,
                    unit=unit,
                    source_name=f"{SOURCE} (achieved sale price)"
                    if field == "sale_price_gbp"
                    else SOURCE,
                    source_url=record["source_url"],
                    doc_span=span.quote,
                    span=span,
                    document_id=document.id,
                    fetched_at=document.fetched_at,
                    observed_at=record["transaction_date"],
                    agent=NAME,
                )
            )
    return [], evidence
