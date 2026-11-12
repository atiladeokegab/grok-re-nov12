"""Coarse public planning, flood and crime context, never property-level findings."""

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime
from urllib.parse import urlencode

import httpx2 as httpx

NAME = "area_context"
POSTCODES_URL = "https://api.postcodes.io/postcodes"
PLANNING_URL = "https://www.planning.data.gov.uk/entity.json"
FLOOD_URL = "https://environment.data.gov.uk/flood-monitoring/id/floods"
POLICE_DATES_URL = "https://data.police.uk/api/crimes-street-dates"
POLICE_CRIME_URL = "https://data.police.uk/api/crimes-street/all-crime"
TIMEOUT = 15


def _get_json(url: str, params=None) -> dict:
    response = httpx.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return {
        "payload": response.json(),
        "raw": response.content,
        "url": str(response.url),
        "content_type": response.headers.get("content-type", "application/json"),
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _unpack(result, url: str, params) -> tuple[dict, bytes, str, str, str]:
    """Return parsed payload plus the original bytes and final URL; dicts are for test fakes."""
    if isinstance(result, dict) and "payload" in result and "raw" in result:
        payload = result["payload"]
        raw = result["raw"]
        final_url = result.get("url") or _with_query(url, params)
        content_type = result.get("content_type", "application/json")
        fetched_at = result.get("fetched_at") or datetime.now(UTC).isoformat()
    else:
        payload = result
        raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
        final_url = _with_query(url, params)
        content_type = "application/json"
        fetched_at = datetime.now(UTC).isoformat()
    return payload, raw, final_url, content_type, fetched_at


def _with_query(url: str, params) -> str:
    if not params:
        return url
    return f"{url}?{urlencode(params, doseq=True)}"


def _results(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("entities", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _available_months(payload) -> list[str]:
    return sorted(
        row["date"]
        for row in _results(payload)
        if isinstance(row.get("date"), str)
        and re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", row["date"])
    )


def _actual_date(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed <= datetime.now(UTC).date() else None


def _quote(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def postcode_point(payload: dict) -> tuple[float, float] | None:
    """Return postcode-centroid (latitude, longitude), never an address point."""
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    lat, lon = result.get("latitude"), result.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def _application_square(lat: float, lon: float, radius_m: int = 200) -> str:
    """Small WGS84 square around the query point; results are nearby area context."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(0.1, abs(math.cos(math.radians(lat)))))
    points = (
        (lon - dlon, lat - dlat),
        (lon + dlon, lat - dlat),
        (lon + dlon, lat + dlat),
        (lon - dlon, lat + dlat),
        (lon - dlon, lat - dlat),
    )
    return "POLYGON((" + ",".join(f"{x} {y}" for x, y in points) + "))"


def _record(kind, source_name, payload, raw, url, content_type, fetched_at, scope):
    return {
        "kind": kind,
        "source_name": source_name,
        "payload": payload,
        "raw": raw,
        "source_url": url,
        "content_type": content_type,
        "fetched_at": fetched_at,
        "agent": NAME,
        "scope": scope,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _fetch(kind, name, url, params, scope, get_json, docs):
    request_url = _with_query(url, params)
    try:
        payload, raw, actual_url, content_type, fetched_at = _unpack(
            get_json(url, params) if params else get_json(url), url, params
        )
    except Exception as exc:
        docs.append(
            {
                "kind": "error",
                "source_name": name,
                "source_kind": kind,
                "source_url": request_url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "agent": NAME,
                "scope": scope,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return None
    doc = _record(kind, name, payload, raw, actual_url, content_type, fetched_at, scope)
    docs.append(doc)
    return payload


def collect(place, listing: dict, get_json=_get_json) -> list[dict]:
    """Fetch bounded APIs. Successful responses retain original bytes for ``land()``."""
    if listing.get("offline"):
        return []
    postcode = "".join((place.postcode or "").upper().split())
    if not postcode:
        return []

    docs = []
    postcode_url = f"{POSTCODES_URL}/{postcode}"
    postcode_data = _fetch(
        "postcode",
        "Postcodes.io",
        postcode_url,
        None,
        "postcode-centroid lookup; geographic context only",
        get_json,
        docs,
    )
    if postcode_data is None:
        return docs
    point = postcode_point(postcode_data)
    if point is None:
        docs.append(
            {
                "kind": "unavailable",
                "source_name": "Postcodes.io",
                "source_url": postcode_url,
                "agent": NAME,
                "scope": "postcode centroid unavailable; no coordinates inferred",
                "reason": "The postcode lookup returned no valid centroid coordinates.",
            }
        )
        return docs

    lat, lon = point
    precision = "postcode centroid (not address coordinates)"
    planning_params = [
        ("dataset", "conservation-area"),
        ("dataset", "planning-application"),
        ("geometry", _application_square(lat, lon)),
        ("geometry_relation", "intersects"),
        ("limit", "50"),
    ]
    _fetch(
        "planning",
        "Planning Data API",
        PLANNING_URL,
        planning_params,
        f"planning query within about 200 m of {precision}; coverage varies; max 50 results; "
        "nearby context only",
        get_json,
        docs,
    )
    flood_params = {"lat": lat, "long": lon, "dist": 1}
    _fetch(
        "flood_alerts",
        "Environment Agency flood monitoring API",
        FLOOD_URL,
        flood_params,
        f"current alerts within 1 km of {precision}; not an address-level flood assessment",
        get_json,
        docs,
    )

    dates = _fetch(
        "police_dates",
        "Police.uk API",
        POLICE_DATES_URL,
        None,
        "available street-crime data months; not an address-level measure",
        get_json,
        docs,
    )
    available = _available_months(dates or [])
    if available:
        crime_month = available[-1]
        crime_params = {"lat": lat, "lng": lon, "date": crime_month}
        _fetch(
            "police_crimes",
            "Police.uk API",
            POLICE_CRIME_URL,
            crime_params,
            f"street-level crimes within about 1 mile of {precision}; incidents are "
            "anonymised approximate locations. Scotland coverage is BTP-only.",
            get_json,
            docs,
        )
    elif dates is not None:
        docs.append(
            {
                "kind": "unavailable",
                "source_name": "Police.uk API",
                "source_url": POLICE_DATES_URL,
                "agent": NAME,
                "scope": f"street-level coverage around {precision}",
                "reason": "The availability endpoint returned no month that could be selected.",
            }
        )
    return docs


def parse_context(docs: list[dict]) -> list[dict]:
    """Build evidence values from collected payloads; keep query errors explicit."""
    out = []
    for doc in docs:
        kind, payload = doc.get("kind"), doc.get("payload")
        if kind == "error":
            out.append(
                {
                    "field": "area_context",
                    "value": {
                        "source": doc["source_name"],
                        "status": "unavailable",
                        "reason": doc["error"],
                    },
                    "scope": doc["scope"],
                    "source_url": doc["source_url"],
                    "fetched_at": doc["fetched_at"],
                    "quote": None,
                }
            )
        elif kind == "unavailable":
            out.append(
                {
                    "field": "area_context",
                    "value": {
                        "source": doc["source_name"],
                        "status": "unavailable",
                        "reason": doc["reason"],
                    },
                    "scope": doc["scope"],
                    "source_url": doc["source_url"],
                    "fetched_at": doc.get("fetched_at"),
                    "quote": None,
                }
            )
        elif kind == "postcode":
            point = postcode_point(payload)
            if point:
                result = payload.get("result", {})
                value = {
                    key: result[key]
                    for key in ("postcode", "latitude", "longitude", "admin_district", "region")
                    if result.get(key) is not None
                }
                value["precision"] = "postcode centroid; not a property coordinate"
                out.append(
                    {
                        "field": "area_context",
                        "value": value,
                        "scope": doc["scope"],
                        "source_url": doc["source_url"],
                        "fetched_at": doc["fetched_at"],
                        "quote": _quote(payload["result"]),
                    }
                )
        elif kind == "planning":
            entities = [
                entity
                for entity in _results(payload)
                if entity.get("dataset") in {"conservation-area", "planning-application"}
            ]
            if not entities:
                out.append(
                    {
                        "field": "area_context",
                        "value": {
                            "result": "no records returned",
                            "coverage": (
                                "planning data coverage varies; absence does not prove no "
                                "designation or application"
                            ),
                        },
                        "scope": doc["scope"],
                        "source_url": doc["source_url"],
                        "fetched_at": doc["fetched_at"],
                        "quote": "[]",
                    }
                )
            for entity in entities:
                value = {
                    key: entity[key]
                    for key in (
                        "name",
                        "dataset",
                        "reference",
                        "start-date",
                        "decision-date",
                        "application-date",
                        "decision",
                        "status",
                    )
                    if entity.get(key) is not None
                }
                out.append(
                    {
                        "field": "area_context",
                        "value": value,
                        "scope": doc["scope"],
                        "source_url": doc["source_url"],
                        "fetched_at": doc["fetched_at"],
                        "quote": _quote(entity),
                    }
                )
                if entity.get("dataset") == "planning-application":
                    label = entity.get("name") or entity.get("reference") or "application record"
                    application_date = _actual_date(entity.get("application-date"))
                    if application_date:
                        out.append(
                            {
                                "field": "nearby_planning_application",
                                "value": f"Nearby planning application: {label}",
                                "observed_at": application_date,
                                "scope": "Nearby area event; not an application for this property",
                                "source_url": doc["source_url"],
                                "fetched_at": doc["fetched_at"],
                                "quote": _quote(entity),
                            }
                        )
                    decision_date = _actual_date(entity.get("decision-date"))
                    if decision_date:
                        decision = entity.get("decision") or entity.get("status") or label
                        out.append(
                            {
                                "field": "nearby_planning_decision",
                                "value": f"Nearby planning decision: {decision}",
                                "observed_at": decision_date,
                                "scope": "Nearby area event; not a decision about this property",
                                "source_url": doc["source_url"],
                                "fetched_at": doc["fetched_at"],
                                "quote": _quote(entity),
                            }
                        )
        elif kind == "flood_alerts":
            alerts = _results(payload)
            items = [
                {
                    key: item[key]
                    for key in (
                        "description",
                        "severity",
                        "severityLevel",
                        "timeRaised",
                        "timeMessageChanged",
                        "floodAreaID",
                    )
                    if item.get(key) is not None
                }
                for item in alerts
            ]
            value = (
                items
                if items
                else {
                    "result": "no current alert returned within the query radius",
                    "scope": "absence does not establish flood-free status",
                }
            )
            out.append(
                {
                    "field": "area_context",
                    "value": value,
                    "scope": doc["scope"],
                    "source_url": doc["source_url"],
                    "fetched_at": doc["fetched_at"],
                    "quote": (_quote(_results(payload)[0]) if alerts else "[]"),
                }
            )
        elif kind == "police_dates":
            dates = _available_months(payload)
            if dates:
                latest = next(row for row in _results(payload) if row.get("date") == dates[-1])
                out.append(
                    {
                        "field": "area_context",
                        "value": {"latest_available_month": dates[-1]},
                        "scope": doc["scope"],
                        "source_url": doc["source_url"],
                        "fetched_at": doc["fetched_at"],
                        "quote": _quote(latest),
                    }
                )
        elif kind == "police_crimes":
            crimes = _results(payload)
            by_category = {}
            by_street = {}
            for crime in crimes:
                category = crime.get("category")
                if category:
                    by_category[category] = by_category.get(category, 0) + 1
                street = (crime.get("location") or {}).get("street", {}).get("name")
                if street:
                    by_street[street] = by_street.get(street, 0) + 1
            if crimes:
                value = {
                    "month": crimes[0].get("month"),
                    "records_returned": len(crimes),
                    "category_counts": by_category,
                    "approximate_street_counts": dict(
                        sorted(by_street.items(), key=lambda item: (-item[1], item[0]))[:10]
                    ),
                    "scope_note": (
                        "Street-level reports are approximate and anonymised, within about "
                        "1 mile of postcode centroid; not property-specific or a safety "
                        "assessment. Scotland coverage is BTP-only."
                    ),
                }
                quote = _quote(crimes[0])
            else:
                value = {
                    "result": "no records returned for selected month and query area",
                    "scope_note": "an empty response does not establish no crime or safety",
                }
                quote = "[]"
            out.append(
                {
                    "field": "area_context",
                    "value": value,
                    "scope": doc["scope"],
                    "source_url": doc["source_url"],
                    "fetched_at": doc["fetched_at"],
                    **({"quote": quote} if quote else {}),
                }
            )
    return out


def ingest(place, listing: dict):
    """Land every raw API response and return evidence tied to verifiable text spans."""
    from starter.core.ingest import decoded_text, ground, land
    from starter.core.xray import Evidence

    docs = collect(place, listing)
    evidence = []
    field_counts = {}
    for doc in docs:
        document = None
        text = ""
        if "raw" in doc:
            document = land(
                listing,
                raw=doc["raw"],
                source_url=doc["source_url"],
                agent=NAME,
                content_type=doc["content_type"],
                fetched_at=doc["fetched_at"],
            )
            text = decoded_text(document) or ""
        for item in parse_context([doc]):
            quote = item.get("quote")
            span = ground(text, quote) if document and quote else None
            if quote and span is None:
                continue
            index = field_counts.get(item["field"], 0) + 1
            evidence.append(
                Evidence(
                    id=f"ev-{NAME}-{listing['listing_id']}-{item['field']}-{index}",
                    place_id=place.id,
                    field=item["field"],
                    value=item["value"],
                    source_name=doc["source_name"],
                    source_url=item.get("source_url", doc.get("source_url")),
                    doc_span=(
                        span.quote
                        if span
                        else (
                            item.get("value", {}).get("reason")
                            if isinstance(item.get("value"), dict)
                            else None
                        )
                    ),
                    document_id=document.id if document else None,
                    span=span,
                    fetched_at=item.get("fetched_at")
                    or doc.get("fetched_at")
                    or datetime.now(UTC).isoformat(),
                    agent=NAME,
                    observed_at=item.get("observed_at"),
                )
            )
            field_counts[item["field"]] = field_counts.get(item["field"], 0) + 1
    return [], evidence
