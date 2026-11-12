"""X-ray scenarios S1, S3, S4, S5 (offline, fixtures) and the HTTP surface."""

import time

from fastapi.testclient import TestClient

from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.core.xray import Claim, Evidence, SourceStatus, trust_score
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals.reconcile import reconcile
from starter.verticals.sources import epc
from starter.verticals.xray import run_xray


def _gateway(tmp_path):
    return build_gateway(Store(tmp_path / "s.json"))


def test_s1_offline_demo_scores_and_cites_every_finding(tmp_path):
    r = run_xray(_gateway(tmp_path), "demo", offline=True)
    assert r.status == "done" and r.trust_score is not None
    status = {s.name: s.status for s in r.sources}
    assert status["listing_history"] == status["epc"] == "ok"  # other registered sources may add
    evidence = {e.id: e for e in r.evidence}
    for f in r.findings:
        if f.verdict != "unverifiable":
            assert f.evidence_ids and all(evidence[i].source_url for i in f.evidence_ids)


def test_demo_property_type_disagrees_with_the_register(tmp_path):
    r = run_xray(_gateway(tmp_path), "demo", offline=True)
    f = next(f for f in r.findings if f.field == "property_type")
    assert f.verdict == "disagrees" and "End-terrace" in f.reasoning


def _claim(field, value, unit=None):
    return Claim(id=f"c-{field}", place_id="place-x", field=field, value=value, unit=unit)


def _ev(field, value, unit=None, agent="epc"):
    return Evidence(
        id=f"ev-{agent}-{field}",
        place_id="place-x",
        field=field,
        value=value,
        unit=unit,
        source_name="EPC register",
        source_url="https://find-energy-certificate.service.gov.uk/energy-certificate/1",
        agent=agent,
    )


def test_s3_size_and_rating_disagree_citing_the_certificate():
    claims = [_claim("floor_area", 70, "m2"), _claim("energy_rating", "C")]
    evidence = [_ev("floor_area", 52.0, "m2"), _ev("energy_rating", "E")]
    findings = reconcile(claims, evidence, [SourceStatus(name="epc", status="ok")])
    assert {f.field: f.verdict for f in findings} == {
        "floor_area": "disagrees",
        "energy_rating": "disagrees",
    }
    assert all("certificate" in e.source_url for e in evidence)
    assert "70" in findings[0].reasoning and "52" in findings[0].reasoning


def test_size_in_sqft_within_tolerance_matches():
    findings = reconcile([_claim("floor_area", 900, "sq ft")], [_ev("floor_area", 84.0, "m2")], [])
    assert findings[0].verdict == "matches"


def test_s4_source_down_is_unverifiable_never_matches():
    status = [SourceStatus(name="epc", status="error", detail="ConnectError: timed out")]
    findings = reconcile([_claim("energy_rating", "C")], [], status)
    assert [f.verdict for f in findings] == ["unverifiable"]
    assert "timed out" in findings[0].reasoning
    assert trust_score(findings) is None


def test_crawl_disagreeing_is_a_flag_and_agreeing_is_not_a_match():
    claims = [_claim("price", 770000.0, "GBP"), _claim("tenure", "Freehold")]
    evidence = [
        _ev("price", 700000.0, "GBP", agent="listing_history"),
        _ev("tenure", "Freehold", agent="listing_history"),
    ]
    findings = reconcile(claims, evidence, [])
    assert [(f.field, f.verdict) for f in findings] == [
        ("price", "flag"),
        ("tenure", "unverifiable"),
    ]


def test_epc_row_match_picks_the_flat_not_its_neighbour():
    rows = [
        "Flat 1 Some Point, 1, High Street, LONDON, E1 1AA C 1 May 2030 | /energy-certificate/a",
        "Flat 12 Some Point, 1, High Street, LONDON, E1 1AA B 1 May 2030 | /energy-certificate/b",
    ]
    assert (
        epc.match_row(rows, "Lot 4 Flat 12 Some Point, 1 High Street, London")
        == "/energy-certificate/b"
    )
    assert epc.match_row(rows, "Flat 9 Some Point, 1 High Street, London") is None


def test_http_run_report_events_and_graph(tmp_path):
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
        assert report["status"] == "done" and report["history"]
        assert "client_calls" in report and report["place"]["photos"]
        body = client.get(f"/api/xray/{run_id}/events").text
        assert "event: finding" in body and body.rstrip().endswith('"error": null}')
        graph = client.get(f"/api/place/{report['place_id']}/graph").json()
        assert {e["kind"] for e in graph["edges"]} >= {"has", "cites", "checked_by"}
        assert (
            client.post("/api/xray", json={"listing_id": "nope", "offline": True}).status_code
            == 404
        )


def test_fixture_names_cannot_walk_the_filesystem():
    import pytest

    from starter.core.errors import NotFound
    from starter.verticals.sources import load_listing

    with pytest.raises(NotFound):
        load_listing("../fixtures/demo", offline=True)


def test_house_is_not_a_flat():
    findings = reconcile([_claim("property_type", "House")], [_ev("property_type", "Flat")], [])
    assert findings[0].verdict == "disagrees"


def test_epc_match_needs_the_same_building():
    from starter.verticals.sources.epc import match_row

    rows = [
        "Flat 1, 20 High Street, LONDON, E1 1AA D 3 May 2030 | /c/20",
        "Flat 1, 10 High Street, LONDON, E1 1AA C 3 May 2030 | /c/10",
    ]
    assert match_row(rows, "Flat 1, 10 High Street, London E1 1AA") == "/c/10"
    assert match_row(rows, "Flat 1, 30 High Street, London E1 1AA") is None


def test_advert_floor_area_is_a_claim():
    from starter.verticals.sources.listing_history import parse_advert

    assert parse_advert("Gross internal area 70 m2 approx")["floor_area"][:2] == (70.0, "m2")
    assert parse_advert("approx 753 sq ft")["floor_area"][:2] == (753.0, "sq ft")


def test_rent_basis_is_never_compared_with_a_sale_price():
    from starter.verticals.sources.listing_history import _crawl_values

    rent = _crawl_values({"price_gbp": "24000", "price_basis": "rent pa"})
    assert "price" not in rent and rent["rent_pa"][0] == 24000.0
    assert "price" not in _crawl_values({"price_gbp": "30", "price_basis": "rent psf"})
    assert "price" in _crawl_values({"price_gbp": "750000", "price_basis": "guide/asking"})


def test_sources_after_the_advert_page_run_in_parallel(monkeypatch):
    import time as _time
    from types import SimpleNamespace

    from starter.verticals import xray as xv

    mods = [SimpleNamespace(NAME=n) for n in ("listing_history", "a", "b", "c")]
    monkeypatch.setattr(xv, "SOURCES", mods)

    class Slow:
        def call(self, name, args, case_id):
            _time.sleep(0.3)
            return {"payload": {"claims": [], "evidence": []}}

    t = _time.perf_counter()
    order = [m.NAME for m, _ in xv._fetch_all(Slow(), "r")]
    assert order[0] == "listing_history" and sorted(order[1:]) == ["a", "b", "c"]
    assert _time.perf_counter() - t < 0.9  # 0.3 first, then a, b, c together: not 1.2 in series


def test_a_run_writes_the_store_once_per_step_not_once_per_event(tmp_path):
    from starter.core.gateway import build_gateway
    from starter.core.store import Store
    from starter.verticals import xray as xv

    store = Store(tmp_path / "s.json")
    writes = []
    real = store.mutate
    store.mutate = lambda fn: (writes.append(1), real(fn))[1]
    xv.run_xray(build_gateway(store), "demo", offline=True)
    events = [e for e in store.snapshot()["events"] if e["type"] == "xray"]
    # start + per source (tool_call audit + one flush) + final score + done: GCS takes ~1 write/s
    assert len(writes) <= 3 + 2 * len(xv.SOURCES) + 2 < len(events)
    seqs = [e["seq"] for e in store.snapshot()["events"]]
    assert seqs == list(range(1, len(seqs) + 1))  # batched and audited events share one sequence


def test_score_events_are_never_null_and_never_repeat(tmp_path):
    import json as _json

    from starter.core.gateway import build_gateway
    from starter.core.store import Store
    from starter.verticals import xray as xv

    store = Store(tmp_path / "s.json")
    xv.run_xray(build_gateway(store), "demo", offline=True)
    ev = [e for e in store.snapshot()["events"] if e["type"] == "xray"]
    scores = [e["data"] for e in ev if e["kind"] == "score"]
    assert scores and all(s["trust_score"] is not None for s in scores)
    dumps = [_json.dumps(s, sort_keys=True) for s in scores]
    assert all(a != b for a, b in zip(dumps, dumps[1:], strict=False))  # only on change
    assert scores[-1]["trust_score"] == 67
    finds = [_json.dumps(e["data"], sort_keys=True) for e in ev if e["kind"] == "finding"]
    assert len(finds) == len(set(finds))  # the same finding is never re-sent unchanged


def test_auction_lot_prefix_is_not_part_of_the_address():
    from starter.verticals.sources import LOT, load_listing

    for raw in ("Lot 8 24 Macquarie Way", "LOT 12 - 24 Macquarie Way", "Lot 3: 24 Macquarie Way"):
        assert LOT.sub("", raw) == "24 Macquarie Way"
    assert LOT.sub("", "Lotus House, 1 Lot Street") == "Lotus House, 1 Lot Street"
    place, _ = load_listing("demo", offline=True)
    assert place.address == "24 Macquarie Way, Isle of Dogs, London, E14 3AU"


def test_sale_status_quote_carries_the_amount():
    from starter.core.ingest import ground
    from starter.verticals.sources.listing_history import parse_advert

    text = "Lot 8 Sold £750,000 End-terrace house"
    value, _, quote = parse_advert(text)["sale_status"]
    assert (value, quote) == ("Sold", "Sold £750,000")
    span = ground(text, quote)
    assert text[span.start : span.end] == span.quote == "Sold £750,000"


def test_offline_run_makes_no_paid_model_calls(tmp_path, monkeypatch):
    import starter.verticals.xray as xv

    def paid(*a, **k):
        raise AssertionError("offline run called a paid model")

    monkeypatch.setattr(xv, "narrate", paid)
    monkeypatch.setattr(xv.cursor_step, "summarize", paid)
    r = run_xray(_gateway(tmp_path), "demo", offline=True)
    assert r.status == "done" and r.trust_score == 67
    assert r.grok_calls == 0 and r.client_calls.cursor_sdk == 0


def test_source_threads_never_wait_on_the_store_and_every_source_call_is_still_audited(tmp_path):
    import threading

    from starter.verticals import xray as xv

    class SlowStore(Store):  # live GCS: a write per source thread queued behind other runs
        def mutate(self, fn):
            if threading.current_thread() is not threading.main_thread():
                raise AssertionError("a source thread wrote the store")
            return super().mutate(fn)

        def publish(self, event):
            return self.mutate(lambda d: d.setdefault("events", []).append(event))

    store = SlowStore(tmp_path / "s.json")
    r = xv.run_xray(build_gateway(store), "demo", offline=True)
    assert r.status == "done" and r.trust_score == 67
    calls = [e["tool"] for e in store.snapshot()["events"] if e.get("type") == "tool_call"]
    ran = [f"source_{s.name}" for s in r.sources if s.status != "off"]  # off raises: no audit
    assert ran and sorted(calls) == sorted(ran)
