"""Traceable ingestion: land dedups by sha256, ground repairs or drops quotes, and a demo
finding traces place -> document -> evidence -> finding over HTTP."""

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from starter.core.gateway import build_gateway
from starter.core.ingest import decoded_text, ground, land
from starter.core.store import Store
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals.xray import run_xray


@pytest.fixture(autouse=True)
def _docs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "docs"))


def test_land_dedups_by_sha256():
    listing: dict = {}
    a = land(listing, raw="<p>Hello</p>", source_url="https://x/1", agent="t")
    b = land(listing, raw=b"<p>Hello</p>", source_url="https://x/2", agent="t")
    sha = hashlib.sha256(b"<p>Hello</p>").hexdigest()
    assert a is b and a.sha256 == sha and a.id == "doc-" + sha[:16] and a.size == 12
    assert listing["_documents"] == [a]
    assert decoded_text(a) == "Hello"
    land(listing, raw="other", source_url="https://x/1", agent="t", content_type="text/plain")
    assert len(listing["_documents"]) == 2


def test_ground_exact_repaired_and_missing():
    text = "The energy rating is D.  Total floor\n area 84 square metres"
    s = ground(text, "energy rating is D")
    assert s and text[s.start : s.end] == s.quote == "energy rating is D"
    s = ground(text, "Total floor area 84")  # whitespace differs: offsets repaired onto text
    assert s and text[s.start : s.end] == s.quote and s.quote.startswith("Total floor")
    assert ground(text, "rating is A") is None
    assert ground(text, "") is None


def test_demo_run_lands_documents_and_grounds_evidence(tmp_path):
    r = run_xray(build_gateway(Store(tmp_path / "s.json")), "demo", offline=True)
    assert r.documents and {d.agent for d in r.documents} >= {"listing_history", "epc"}
    grounded = [e for e in r.evidence if e.span]
    assert grounded and all(e.document_id for e in grounded)


def test_trace_and_document_routes(tmp_path):
    app = create_app(Settings(data_path=str(tmp_path / "s.json")))
    with TestClient(app) as client:
        run_id = client.post("/api/xray", json={"listing_id": "demo", "offline": True}).json()[
            "run_id"
        ]
        for _ in range(50):
            report = client.get(f"/api/xray/{run_id}").json()
            if report["status"] != "running":
                break
            time.sleep(0.1)
        assert report["status"] == "done"
        assert all("bytes_path" not in d for d in report["documents"])
        traces = [
            client.get(f"/api/finding/{f['id']}/trace", params={"run_id": run_id}).json()
            for f in report["findings"]
        ]
        t = next(t for t in traces if any(s["quote_verified"] for s in t["steps"]))
        assert [c["kind"] for c in t["chain"]] == ["place", "document", "evidence", "finding"]
        doc_id = t["chain"][1]["id"]
        doc = client.get(f"/api/document/{doc_id}").json()
        step = next(s for s in t["steps"] if s["quote_verified"])
        span = step["evidence"]["span"]
        assert doc["text"][span["start"] : span["end"]] == span["quote"]
        assert "bytes_path" not in doc["document"]
        raw = client.get(doc["raw_url"])
        assert raw.status_code == 200 and raw.content
        assert client.get(f"/api/finding/{t['finding']['id']}/trace").json()["run_id"] == run_id
        graph = client.get(f"/api/place/{report['place_id']}/graph").json()
        assert {e["kind"] for e in graph["edges"]} >= {"landed", "contains"}
        body = client.get(f"/api/xray/{run_id}/events").text
        for kind in ("landed", "parsed", "extracted", "linked"):
            assert f"event: ingestion.{kind}" in body
        assert client.get("/api/document/doc-nope").status_code == 404
        assert client.get("/api/document/doc-nope/raw").status_code == 404
        assert client.get("/api/finding/f-nope/trace").status_code == 404
