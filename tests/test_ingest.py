"""Traceable ingestion: land dedups by sha256, ground repairs or drops quotes, and a demo
finding traces place -> document -> evidence -> finding over HTTP."""

import hashlib
import importlib.util
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from starter.core.gateway import build_gateway
from starter.core.ingest import decoded_text, ground, land
from starter.core.store import Store
from starter.core.xray import Claim, Evidence, SourceStatus
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals.reconcile import reconcile
from starter.verticals.xray import _history, run_xray

ROOT = Path(__file__).resolve().parent.parent


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
    crawl = next(d for d in r.documents if d.url.endswith("#crawl"))
    price = next(e for e in r.evidence if e.id.startswith("ev-crawl-") and e.field == "price")
    assert price.document_id == crawl.id and price.span.quote == "price_gbp=770000.0"
    assert all(c.span and c.document_id for c in r.claims)  # every advert quote grounds


def test_undated_area_context_is_an_info_flag():
    ev = _observed("area_context", "Flood zone 1")
    ev.observed_at = None
    [f] = reconcile([], [ev], [SourceStatus(name="wayback", status="ok")])
    assert (f.verdict, f.severity) == ("flag", "info")


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
        kinds = [c["kind"] for c in t["chain"]]
        assert kinds == ["place", "document", "claim", "document", "evidence", "finding"]
        assert t["claim_quote_verified"] and t["claim"]["document_id"] == t["chain"][1]["id"]
        doc_id = t["chain"][3]["id"]
        doc = client.get(f"/api/document/{doc_id}").json()
        step = next(s for s in t["steps"] if s["quote_verified"])
        span = step["evidence"]["span"]
        assert doc["text"][span["start"] : span["end"]] == span["quote"]
        assert "bytes_path" not in doc["document"]
        raw = client.get(doc["raw_url"])
        assert raw.status_code == 200 and raw.content
        assert raw.headers["content-disposition"] == f'attachment; filename="{doc_id}.txt"'
        assert raw.headers["x-content-type-options"] == "nosniff"
        assert raw.headers["content-security-policy"] == "sandbox"
        assert raw.headers["content-type"].startswith(doc["document"]["content_type"])
        assert client.get(f"/api/finding/{t['finding']['id']}/trace").json()["run_id"] == run_id
        graph = client.get(f"/api/place/{report['place_id']}/graph").json()
        assert {e["kind"] for e in graph["edges"]} >= {"landed", "contains"}
        body = client.get(f"/api/xray/{run_id}/events").text
        for kind in ("landed", "parsed", "extracted", "linked"):
            assert f"event: ingestion.{kind}" in body
        assert client.get("/api/document/doc-nope").status_code == 404
        assert client.get("/api/document/doc-nope/raw").status_code == 404
        assert client.get("/api/finding/f-nope/trace").status_code == 404


def _observed(field, value, agent="wayback"):
    return Evidence(
        id=f"ev-{agent}-{field}",
        place_id="place-x",
        field=field,
        value=value,
        source_name="Wayback",
        agent=agent,
        observed_at="2019-04-02",
    )


def test_observed_evidence_is_history_not_a_current_check():
    claims = [Claim(id="c-rating", place_id="place-x", field="energy_rating", value="C")]
    evidence = [_observed("energy_rating", "E"), _observed("floor_area", 50.0)]
    findings = reconcile(claims, evidence, [SourceStatus(name="wayback", status="ok")])
    assert not any(set(f.evidence_ids) & {e.id for e in evidence} for f in findings)
    assert [f.verdict for f in findings if f.field == "energy_rating"] == ["unverifiable"]
    history = _history(claims, evidence)
    assert [h.observed_at for h in history] == ["2019-04-02", "2019-04-02"]
    assert all(h.fetched_at != "2019-04-02" for h in history)  # retrieved now, true then


def test_smoke_counts_a_history_only_source_as_covered(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("xray_script", ROOT / "scripts/xray.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    def run_with_history_source(gateway, ref, offline=False):
        r = run_xray(gateway, ref, offline)
        r.sources.append(SourceStatus(name="wayback", status="ok", n_evidence=1))
        r.evidence.append(_observed("price", 400000.0))
        return r

    monkeypatch.setattr(script, "run_xray", run_with_history_source)
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "s.json"))
    assert script.main(["--fixture", "demo"]) == 0
