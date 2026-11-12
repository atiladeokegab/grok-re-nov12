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
