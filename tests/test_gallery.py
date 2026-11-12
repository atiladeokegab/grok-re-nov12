"""The 'try these' gallery: real crawl listings, each replayed offline to its discrepancy."""

from fastapi.testclient import TestClient

from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals.xray import run_xray


def _findings(tmp_path, name):
    r = run_xray(build_gateway(Store(tmp_path / "s.json")), name, offline=True)
    assert r.status == "done"
    return {f.field: f for f in r.findings}


def test_price_history_flags_the_crawl_price(tmp_path):
    f = _findings(tmp_path, "sleaford-house")["price"]
    assert f.verdict == "flag" and "£180,000" in f.reasoning and "£120,000" in f.reasoning


def test_photo_reuse_flags_the_earlier_sold_lot(tmp_path):
    f = _findings(tmp_path, "charlemont-road")["photo_reuse"]
    assert f.verdict == "flag" and f.severity == "warn"
    assert "7 of 8 photos" in f.reasoning and "lot/152997" in f.reasoning


def test_area_disagrees_with_the_epc(tmp_path):
    found = _findings(tmp_path, "kimberley-road")
    f = found["floor_area"]
    assert f.verdict == "disagrees" and "81 m2" in f.reasoning and "72 m2" in f.reasoning
    assert found["property_type"].verdict == "matches"  # "Terraced" is the EPC's mid-terrace


def test_gallery_lists_three_real_listings(tmp_path):
    app = create_app(Settings(data_path=str(tmp_path / "s.json")))
    with TestClient(app) as client:
        items = client.get("/api/gallery").json()
    assert {i["discrepancy"] for i in items} == {"price_history", "photo_reuse", "area_type"}
    banned = ("regatta", "manilla", "canada square")
    assert not any(b in i["title"].lower() for i in items for b in banned)
