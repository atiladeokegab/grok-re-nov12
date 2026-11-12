"""Paste anything: any URL or text gives a normal answer, never a 500, inside the time budget."""

import json
import threading
import time

import httpx2
import pytest
from fastapi.testclient import TestClient

from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals import xray
from starter.verticals.sources import SOURCES, listing_history

GARBAGE = [
    "hello",
    "   ",
    "x" * 300_000,
    "1" * 150_000,
    "café ünïcödé 💥 \ud800 \x00",
    "<script>alert(1)</script>",
    "ftp://example.com/x",
    "http://169.254.169.254/latest/meta-data",
    "https://www.rightmove.co.uk/properties/123456789",
    "https://www.zoopla.co.uk/for-sale/details/1/",
    "https://www.openrent.co.uk/property-to-rent/london/2-bed-flat/1",
    "https://www.rightmove.co.uk/" + "a" * 5000,
]


@pytest.fixture
def no_network(monkeypatch):
    """Advert sites answer 403, like Rightmove does to a bot; nothing else may be fetched."""
    calls = []

    def get_text(url, params=None):
        calls.append(url)
        req = httpx2.Request("GET", url)
        raise httpx2.HTTPStatusError("403", request=req, response=httpx2.Response(403, request=req))

    monkeypatch.setattr(listing_history, "get_text", get_text)
    return calls


@pytest.mark.parametrize("ref", GARBAGE, ids=range(len(GARBAGE)))
def test_any_paste_is_a_normal_answer_never_a_500(tmp_path, no_network, ref):
    app = create_app(Settings(data_path=str(tmp_path / "s.json")))
    with TestClient(app, raise_server_exceptions=False) as client:
        body = json.dumps({"url": ref})  # ASCII escapes: a lone surrogate reaches the server
        r = client.post("/api/xray", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        for _ in range(100):
            report = client.get(f"/api/xray/{run_id}").json()
            if report["status"] != "running":
                break
            time.sleep(0.05)
    assert report["status"] == "done", report["error"]
    assert report["message"].startswith("Couldn't read this listing")
    assert all(not u.startswith(("ftp:", "http://169")) for u in no_network)


def test_empty_paste_is_a_422_not_a_500(tmp_path):
    app = create_app(Settings(data_path=str(tmp_path / "s.json")))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/xray", json={"url": ""}).status_code == 422


def test_mcp_and_run_xray_take_garbage_too(tmp_path, no_network):
    app = create_app(Settings(data_path=str(tmp_path / "s.json")))
    out = app.state.gateway.call("xray_listing", {"listing_id_or_url": "?? not a listing"}, "t")
    assert out["payload"]["message"].startswith("Couldn't read this listing")
    gw = build_gateway(Store(tmp_path / "s2.json"))
    assert xray.run_xray(gw, "https://www.zoopla.co.uk/x").status == "done"


def test_pasted_advert_text_is_read_and_unreadable_keeps_what_was_read(tmp_path):
    gw = build_gateway(Store(tmp_path / "s.json"))
    text = "Lovely flat, Guide £350,000. Two Bedrooms. Tenure: Leasehold. London E14 9AB"
    r = xray.run_xray(gw, text)
    assert r.message is None and r.place.postcode == "E14 9AB"
    assert {c.field: c.value for c in r.claims}.items() >= {("price", 350000.0), ("bedrooms", 2)}
    r = xray.run_xray(gw, "nice place near the park, SW1A 1AA")
    assert r.status == "done" and r.place.postcode == "SW1A 1AA"
    assert r.message == (
        "Couldn't read this listing: no price, bedrooms, floor area, tenure or energy rating "
        "found in it. Read anyway: postcode."
    )


@pytest.mark.parametrize("hung", [m.NAME for m in SOURCES if m.NAME != listing_history.NAME])
def test_a_hung_source_is_cut_off_and_the_score_still_lands(tmp_path, monkeypatch, hung):
    slow = next(m for m in SOURCES if m.NAME == hung)
    release = threading.Event()

    def hang(place, listing):
        release.wait(30)  # hangs until the test ends
        return [], []

    monkeypatch.setattr(slow, "ingest", hang)
    gw = build_gateway(Store(tmp_path / "s.json"))
    monkeypatch.setattr(xray, "BUDGET_S", 0.5)
    start = time.monotonic()
    try:
        r = xray.run_xray(gw, "demo", offline=True)
    finally:
        release.set()
    assert time.monotonic() - start < 2
    # the demo's only scored evidence is the EPC's: without it there is nothing to score
    assert r.trust_score is not None or hung == "epc"
    s = next(s for s in r.sources if s.name == slow.NAME)
    assert (s.status, s.detail) == ("error", "timed out after 0.5 s")
    assert r.status == "done" and r.claims  # the advert still read
