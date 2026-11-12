import hashlib
import json

import pytest

from starter.verticals.sources.area_context import collect, parse_context, postcode_point


class Place:
    postcode = "SW1A 1AA"


def result(url, params, payload):
    query = ""
    if params:
        from urllib.parse import urlencode

        query = "?" + urlencode(params, doseq=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "payload": payload,
        "raw": raw,
        "url": url + query,
        "content_type": "application/json",
        "fetched_at": "2026-11-12T12:00:00Z",
    }


def test_postcode_point_is_centroid_and_validated():
    assert postcode_point({"result": {"latitude": 51.5, "longitude": -0.12}}) == (
        51.5,
        -0.12,
    )
    assert postcode_point({"result": {"latitude": 100, "longitude": 2}}) is None
    assert postcode_point({"status": 404}) is None


def test_collect_lands_exact_response_bytes_and_latest_police_month():
    calls = []

    def fake_get(url, params=None):
        calls.append((url, params))
        if "postcodes.io" in url:
            payload = {"status": 200, "result": {"latitude": 51.5, "longitude": -0.12}}
        elif "planning.data.gov.uk" in url:
            payload = {
                "entities": [
                    {
                        "dataset": "planning-application",
                        "name": "Application A",
                        "application-date": "2025-02-03",
                    }
                ]
            }
        elif "flood-monitoring" in url:
            payload = {"items": []}
        elif url.endswith("crimes-street-dates"):
            payload = [{"date": "2026-08"}, {"date": "2026-09"}]
        else:
            payload = [
                {
                    "category": "burglary",
                    "month": "2026-09",
                    "location": {"street": {"name": "On or near Example Road"}},
                }
            ]
        return result(url, params, payload)

    docs = collect(Place(), {"offline": False}, fake_get)
    assert [doc["kind"] for doc in docs] == [
        "postcode",
        "planning",
        "flood_alerts",
        "police_dates",
        "police_crimes",
    ]
    for doc in docs:
        assert doc["sha256"] == hashlib.sha256(doc["raw"]).hexdigest()
        assert doc["agent"] == "area_context"
        assert doc["source_url"].startswith("https://")
    assert "postcode centroid" in docs[1]["scope"]
    assert "not an address-level" in docs[2]["scope"]
    assert dict(calls[1][1])["geometry_relation"] == "intersects"
    assert dict(calls[-1][1]) == {"lat": 51.5, "lng": -0.12, "date": "2026-09"}
    assert "dataset=conservation-area" in docs[1]["source_url"]
    assert "geometry_relation=intersects" in docs[1]["source_url"]
    assert "date=2026-09" in docs[-1]["source_url"]
    crime = next(
        item
        for item in parse_context(docs)
        if isinstance(item["value"], dict) and item["value"].get("month") == "2026-09"
    )
    assert crime["value"]["approximate_street_counts"] == {"On or near Example Road": 1}


def test_offline_mode_never_fetches():
    assert collect(Place(), {"offline": True}, lambda *_a, **_k: pytest.fail("network")) == []


def test_missing_centroid_is_explicit_and_does_not_fabricate_coordinates():
    url = "https://api.postcodes.io/postcodes/SW1A1AA"
    docs = collect(
        Place(),
        {"offline": False},
        lambda *_a, **_k: result(url, None, {"status": 404, "result": None}),
    )
    assert [doc["kind"] for doc in docs] == ["postcode", "unavailable"]
    assert "no coordinates inferred" in docs[-1]["scope"]


def test_one_upstream_error_does_not_discard_other_sources_or_look_empty():
    def fake_get(url, params=None):
        if "postcodes.io" in url:
            payload = {"result": {"latitude": 51.5, "longitude": -0.12}}
        elif "planning.data.gov.uk" in url:
            raise RuntimeError("HTTP 503")
        elif "flood-monitoring" in url:
            payload = {"items": []}
        elif url.endswith("crimes-street-dates"):
            payload = [{"date": "2026-09"}]
        else:
            payload = []
        return result(url, params, payload)

    docs = collect(Place(), {"offline": False}, fake_get)
    assert "planning" not in [doc["kind"] for doc in docs]
    assert any(doc["kind"] == "error" and "HTTP 503" in doc["error"] for doc in docs)
    assert "flood_alerts" in [doc["kind"] for doc in docs]
    context = parse_context(docs)
    error_item = next(item for item in context if item["value"].get("status") == "unavailable")
    assert error_item["field"] == "area_context"


def test_no_alert_or_crime_rows_never_claim_safety_or_no_crime():
    context = parse_context(
        [
            {
                "kind": "flood_alerts",
                "payload": {"items": []},
                "scope": "centroid + 1 km",
                "source_url": "https://flood.example/api?lat=1&long=2&dist=1",
                "fetched_at": "2026-11-12T12:00:00Z",
            },
            {
                "kind": "police_crimes",
                "payload": [],
                "scope": "centroid + about 1 mile",
                "source_url": "https://police.example/api?date=2026-09",
                "fetched_at": "2026-11-12T12:00:00Z",
            },
        ]
    )
    text = json.dumps(context).lower()
    assert "does not establish flood-free status" in text
    assert "does not establish no crime or safety" in text
    assert '"safe": true' not in text


def test_planning_dates_are_only_reported_when_returned_and_are_not_history_facts():
    context = parse_context(
        [
            {
                "kind": "planning",
                "payload": {
                    "entities": [
                        {"dataset": "conservation-area", "name": "Area A"},
                        {
                            "dataset": "planning-application",
                            "name": "App A",
                            "application-date": "2025-02-03",
                        },
                    ]
                },
                "scope": "postcode-centroid surroundings",
                "source_url": "https://planning.example/entity.json?geometry=...",
                "fetched_at": "2026-11-12T12:00:00Z",
            }
        ]
    )
    area = [item for item in context if item["field"] == "area_context"]
    dated = [item for item in context if item["field"] == "nearby_planning_application"]
    assert area[0]["value"] == {"dataset": "conservation-area", "name": "Area A"}
    assert area[1]["value"]["application-date"] == "2025-02-03"
    assert len(dated) == 1
    assert dated[0]["observed_at"] == "2025-02-03"
    assert "not an application for this property" in dated[0]["scope"]
    assert all("observed_at" not in item for item in area)


def test_month_only_planning_date_does_not_become_a_dated_event():
    context = parse_context(
        [
            {
                "kind": "planning",
                "payload": {
                    "entities": [
                        {
                            "dataset": "planning-application",
                            "name": "App A",
                            "application-date": "2025-02",
                        }
                    ]
                },
                "scope": "postcode centroid surroundings",
                "source_url": "https://planning.example/entity.json?geometry=...",
                "fetched_at": "2026-11-12T12:00:00Z",
            }
        ]
    )
    assert len(context) == 1
    assert context[0]["field"] == "area_context"
    assert "observed_at" not in context[0]


def test_ingest_lands_original_bytes_and_verifies_span_in_served_json(tmp_path, monkeypatch):
    import starter.verticals.sources.area_context as source
    from starter.core.ingest import decoded_text, raw_bytes

    payload = {
        "items": [
            {
                "description": "River Example",
                "severity": "Flood alert",
                "severityLevel": 3,
                "floodAreaID": "EXAMPLE-1",
            }
        ]
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    captured = {
        "kind": "flood_alerts",
        "source_name": "Environment Agency flood monitoring API",
        "payload": payload,
        "raw": raw,
        "source_url": "https://environment.data.gov.uk/flood-monitoring/id/floods?lat=51.5&long=-0.12&dist=1",
        "content_type": "application/json",
        "fetched_at": "2026-11-12T12:00:00Z",
        "agent": "area_context",
        "scope": "postcode centroid; not address-level",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "store.json"))
    monkeypatch.setattr(source, "collect", lambda *_args: [captured])
    place = type("Place", (), {"id": "place-test"})()
    listing = {"listing_id": "test-property"}

    _claims, evidence = source.ingest(place, listing)
    assert len(evidence) == 1
    assert evidence[0].field == "area_context"
    document = listing["_documents"][0]
    assert raw_bytes(document) == raw
    assert evidence[0].document_id == document.id
    served = decoded_text(document)
    assert served[evidence[0].span.start : evidence[0].span.end] == evidence[0].span.quote
    assert evidence[0].doc_span == evidence[0].span.quote


def test_ingest_grounds_quotes_for_each_public_api_shape(tmp_path, monkeypatch):
    import starter.verticals.sources.area_context as source
    from starter.core.ingest import decoded_text

    payloads = [
        (
            "postcode",
            "Postcodes.io",
            {"result": {"postcode": "SW1A 1AA", "latitude": 51.5, "longitude": -0.12}},
        ),
        (
            "planning",
            "Planning Data API",
            {
                "entities": [
                    {
                        "dataset": "planning-application",
                        "name": "App A",
                        "application-date": "2025-02-03",
                    }
                ]
            },
        ),
        (
            "flood_alerts",
            "Environment Agency flood monitoring API",
            {"items": [{"description": "River A", "severity": "Flood alert", "floodAreaID": "A1"}]},
        ),
        ("police_dates", "Police.uk API", [{"date": "2026-09"}]),
        (
            "police_crimes",
            "Police.uk API",
            [
                {
                    "month": "2026-09",
                    "category": "burglary",
                    "location": {"street": {"name": "On or near Example Road"}},
                }
            ],
        ),
    ]
    docs = []
    for kind, source_name, payload in payloads:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        docs.append(
            {
                "kind": kind,
                "source_name": source_name,
                "payload": payload,
                "raw": raw,
                "source_url": f"https://api.example/{kind}?sample=1",
                "content_type": "application/json",
                "fetched_at": "2026-11-12T12:00:00Z",
                "agent": "area_context",
                "scope": "postcode centroid context",
            }
        )
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "store.json"))
    monkeypatch.setattr(source, "collect", lambda *_args: docs)
    place = type("Place", (), {"id": "place-test"})()
    listing = {"listing_id": "test-property"}
    _claims, evidence = source.ingest(place, listing)

    assert len(evidence) == 6
    assert len({document.id for document in listing["_documents"]}) == 5
    assert sum(item.observed_at is not None for item in evidence) == 1
    for item in evidence:
        document = next(doc for doc in listing["_documents"] if doc.id == item.document_id)
        text = decoded_text(document)
        assert item.span is not None
        assert text[item.span.start : item.span.end] == item.span.quote
        assert item.doc_span == item.span.quote
        assert item.field in {"area_context", "nearby_planning_application"}
