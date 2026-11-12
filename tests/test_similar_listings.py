import csv
import json

import pytest

from starter.verticals import sources
from starter.verticals.sources import load_listing, similar_listings


@pytest.fixture
def crawl(tmp_path, monkeypatch):
    """A local crawl: the demo listing (E14 3-bed house, £770,000) and its neighbours."""
    demo = json.loads((sources.FIXTURES / "demo.json").read_text())["crawl"]

    def like(i, **kw):
        return demo | {"listing_id": f"x-{i}", "url": f"https://example.test/{i}"} | kw

    rows = [
        demo,
        like(1, address="1 A St, London, E14 1AA", price_gbp="700000.0", size_sqft="1000"),
        like(2, address="2 B St, London, E14 2BB", price_gbp="800000.0"),
        like(3, address="3 C St, London, E3 3CC", postcode="E3 3CC", price_gbp="760000.0"),
        like(7, address="7 G St, London, E14 7GG", price_gbp="750000.0"),
        like(4, address="4 D St, London, E14 4DD", property_type="flat"),  # not a house
        like(5, address="5 E St, London, E14 5EE", price_gbp="1750.0"),  # a fee, not a guide
        like(6, address="6 F St, Leeds, LS1 6FF", postcode="LS1 6FF"),  # another area
    ]
    path = tmp_path / "listings.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(demo))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setenv("LISTINGS_CSV", str(path))
    similar_listings._index.cache_clear()
    yield
    similar_listings._index.cache_clear()


def test_demo_run_finds_linked_comparables_offline(crawl, tmp_path):
    from starter.core.gateway import build_gateway
    from starter.core.store import Store
    from starter.verticals.xray import run_xray

    place, listing = load_listing("demo", offline=True)
    (ev,) = similar_listings.ingest(place, listing)[1]
    assert [c["listing_id"] for c in ev.value] == ["x-7", "x-2", "x-1", "x-3"]  # E14 first
    assert ev.value[2]["price_per_m2"] == round(700000 / (1000 * 0.09290304))
    assert all(c["url"].startswith("https://example.test/") for c in ev.value)
    assert ev.doc_span == (
        "3 similar 3-bed houses in E14 list at £700,000–£800,000; "
        "this one asks £770,000, above the median of £750,000."
    )

    # fewer than 3 in the district, and a fee for a price: listed, never compared
    similar_listings._index()["E"][:] = [
        c for c in similar_listings._index()["E"] if c["listing_id"] not in ("x-7", "x-2")
    ]
    listing["crawl"] = listing["crawl"] | {"price_gbp": "1750.0"}
    (ev,) = similar_listings.ingest(place, listing)[1]
    assert [c["listing_id"] for c in ev.value] == ["x-1", "x-3"]
    assert ev.doc_span == (
        "Only 1 other similar house in E14 is in the crawl; the nearest others are in E3, so "
        "this is not a like-for-like price comparison. The crawl's price for this one (£1,750) "
        "is too low to be a guide price (likely a fee), so it is not compared."
    )

    similar_listings._index.cache_clear()
    r = run_xray(build_gateway(Store(tmp_path / "s.json")), "demo", offline=True)
    assert any(f.field == "comparables" for f in r.findings)


def test_no_local_crawl_is_off_not_an_error(monkeypatch, tmp_path):
    from starter.core.errors import SourceOff

    monkeypatch.delenv("LISTINGS_CSV", raising=False)
    monkeypatch.setattr(similar_listings, "SLICE", tmp_path / "missing.csv")
    similar_listings._index.cache_clear()
    place, listing = load_listing("demo", offline=True)
    with pytest.raises(SourceOff):
        similar_listings.ingest(place, listing)
    similar_listings._index.cache_clear()
