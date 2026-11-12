"""Exercise the deployed gallery and demo evidence through the same public HTTP routes."""

import hashlib
import time

import pytest

pytestmark = pytest.mark.live


def test_live_gallery_exposes_replayable_listing_ids(client):
    response = client.get("/api/gallery")
    assert response.status_code == 200, response.text
    items = response.json()
    assert {item["discrepancy"] for item in items} >= {"price_history", "photo_reuse", "area_type"}
    assert all(
        item["name"] and item["listing_id"] and item["url"].startswith("https://") for item in items
    )


def test_live_demo_finishes_with_traceable_evidence(client):
    response = client.post("/api/xray", json={"listing_id": "demo", "offline": True})
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 120
    while True:
        response = client.get(f"/api/xray/{run_id}")
        assert response.status_code == 200, response.text
        report = response.json()
        if report["status"] != "running" or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    assert report["status"] == "done", report.get("error") or report["status"]
    assert isinstance(report["trust_score"], (int, float))
    finding = next(
        f
        for f in report["findings"]
        if f["field"] == "property_type" and f["verdict"] == "disagrees"
    )
    response = client.get(f"/api/finding/{finding['id']}/trace", params={"run_id": run_id})
    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["run_id"] == run_id and trace["claim_quote_verified"]
    assert trace["steps"] and all(step["quote_verified"] for step in trace["steps"])
    for step in trace["steps"]:
        evidence = step["evidence"]
        response = client.get(f"/api/document/{evidence['document_id']}")
        assert response.status_code == 200, response.text
        document = response.json()
        span = evidence["span"]
        assert document["text"][span["start"] : span["end"]] == span["quote"]
        assert "bytes_path" not in document["document"]
        raw = client.get(document["raw_url"])
        assert raw.status_code == 200, raw.text
        assert hashlib.sha256(raw.content).hexdigest() == document["document"]["sha256"]
        assert raw.headers["x-content-type-options"] == "nosniff"
