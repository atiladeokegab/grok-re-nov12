import importlib.util
import json
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

from starter.core.xray import Place

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "atlas_wayback_history", ROOT / "starter/verticals/sources/wayback_history.py"
)
wayback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wayback)

PLACE = Place(
    id="p1", address="Lot 8 24 Macquarie Way, Isle of Dogs, London, E14 3AU", postcode="E14 3AU"
)
URL = "https://portal.example/24"


def test_cdx_sorts_deduplicates_and_limits_distinct_content():
    rows = [["timestamp", "original", "mimetype", "statuscode", "digest"]]
    rows += [
        ["20200101000000", URL, "text/html", "200", "old"],
        ["20210101000000", URL, "text/html", "200", "old"],
        ["20220101000000", URL, "text/html", "200", "new"],
        ["20220101000000", URL, "text/html", "200", "new"],
        ["20230101000000", URL, "application/pdf", "200", "pdf"],
        ["20240101000000", URL, "text/html", "404", "gone"],
    ]
    parsed = wayback.parse_cdx(rows)
    assert [x["timestamp"] for x in parsed] == ["20210101000000", "20220101000000"]
    assert [x["digest"] for x in parsed] == ["old", "new"]


def test_empty_archive_and_unsafe_urls_are_empty():
    assert wayback.parse_cdx([]) == []
    assert wayback.parse_cdx({"error": "no captures"}) == []
    assert wayback._history_urls({"url": "http://127.0.0.1/private"}) == []
    assert wayback._history_urls({"url": "https://user:secret@example.org/item"}) == []


def test_identity_gate_requires_exact_house_and_postcode():
    assert (
        wayback.snapshot_observations(
            PLACE, "<p>Sold £770,000. E14 3AU</p>", "2024-01-01T00:00:00+00:00"
        )
        == []
    )


def test_price_bases_and_floor_area_units_get_separate_history_fields():
    guide = wayback.snapshot_observations(
        PLACE, "<p>24 Macquarie Way, E14 3AU Guide £700,000</p>", "2020-01-01T00:00:00+00:00"
    )[0]
    sold = wayback.snapshot_observations(
        PLACE, "<p>24 Macquarie Way, E14 3AU Sold £770,000</p>", "2021-01-01T00:00:00+00:00"
    )[0]
    assert guide["field"] == "advert_asking_price_gbp"
    assert sold["field"] == "advert_sold_price_gbp"
    assert wayback.snapshot_observations(
        PLACE, "<p>24 Macquarie Way, E14 3AU Guide £770,000</p>", "2024-01-01T00:00:00+00:00"
    )
    assert (
        wayback.snapshot_observations(
            PLACE, "<p>24 Macquarie Way, E14 3AB Guide £770,000</p>", "2024-01-01T00:00:00+00:00"
        )
        == []
    )


def test_flat_requires_unit_building_street_and_postcode():
    flat = Place(
        id="flat",
        address="Flat 2, The Foundry, 69 Johnson Street, London, E1 0AQ",
        postcode="E1 0AQ",
    )
    assert wayback.snapshot_observations(
        flat,
        "<p>Flat 2, The Foundry, 69 Johnson Street, E1 0AQ Guide £500,000</p>",
        "2024-01-01T00:00:00+00:00",
    )
    assert (
        wayback.snapshot_observations(
            flat,
            "<p>Flat 2, 69 Johnson Street, E1 0AQ Guide £500,000</p>",
            "2024-01-01T00:00:00+00:00",
        )
        == []
    )


def test_replay_provenance_rejects_live_or_different_capture():
    response = SimpleNamespace(url="https://www.example.com/page", headers={})
    assert not wayback._response_is_exact_capture(response, "20250101000000")
    response.url = "https://web.archive.org/web/20240101000000id_/https://portal.example/24"
    assert not wayback._response_is_exact_capture(response, "20250101000000")
    response.url = "https://web.archive.org/web/20250101000000id_/https://portal.example/24"
    assert wayback._response_is_exact_capture(response, "20250101000000")
    response.headers["Memento-Datetime"] = "Mon, 01 Jan 2024 00:00:00 GMT"
    assert not wayback._response_is_exact_capture(response, "20250101000000")


class FakeResponse:
    def __init__(self, url, content, text=None, headers=None):
        self.url = url
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")
        self.headers = headers or {}

    def raise_for_status(self):
        pass


def test_ingest_lands_raw_docs_and_emits_two_dated_scalar_values(tmp_path, monkeypatch):
    listing = {"listing_id": "lot-8", "url": URL, "history_urls": [URL, "http://invalid.example/"]}
    bodies = {
        "20200101000000": b"<p>24 Macquarie Way, E14 3AU Guide \xc2\xa3700,000</p>",
        "20220101000000": b"<p>24 Macquarie Way, E14 3AU Guide \xc2\xa3710,000</p>",
    }
    cdx = [["timestamp", "original", "mimetype", "statuscode", "digest"]] + [
        [stamp, URL, "text/html", "200", str(i)] for i, stamp in enumerate(bodies)
    ]
    cdx_raw = json.dumps(cdx).encode()

    def fake_get(url, **kwargs):
        if url == wayback.CDX_URL:
            return FakeResponse(wayback.CDX_URL, cdx_raw)
        stamp = url.split("/web/")[1][:14]
        date = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        return FakeResponse(
            url,
            bodies[stamp],
            headers={
                "Memento-Datetime": format_datetime(date, usegmt=True),
                "content-type": "text/html",
            },
        )

    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(wayback.httpx2, "get", fake_get)
    evidence = wayback.ingest(PLACE, listing)[1]
    assert [item.field for item in evidence] == [
        "advert_asking_price_gbp",
        "advert_asking_price_gbp",
    ]
    assert [item.value for item in evidence] == [700000.0, 710000.0]
    assert [item.observed_at for item in evidence] == [
        "2020-01-01T00:00:00+00:00",
        "2022-01-01T00:00:00+00:00",
    ]
    assert len(listing["_documents"]) == 3  # CDX and two archived HTML payloads
    assert all(item.document_id and item.span.quote == item.doc_span for item in evidence)
    assert all(doc.agent == wayback.NAME for doc in listing["_documents"])
    from starter.core.ingest import decoded_text

    documents = {doc.id: doc for doc in listing["_documents"]}
    for item in evidence:
        document_text = decoded_text(documents[item.document_id])
        assert document_text[item.span.start : item.span.end] == item.span.quote


def test_ingest_rejects_replay_redirect_to_different_capture(tmp_path, monkeypatch):
    listing = {"listing_id": "lot-8", "url": URL}
    html = b"<p>24 Macquarie Way, E14 3AU Guide \xc2\xa3700,000</p>"
    cdx = json.dumps(
        [
            ["timestamp", "original", "mimetype", "statuscode", "digest"],
            ["20200101000000", URL, "text/html", "200", "one"],
        ]
    ).encode()

    def fake_get(url, **kwargs):
        if url == wayback.CDX_URL:
            return FakeResponse(wayback.CDX_URL, cdx)
        redirected = "https://web.archive.org/web/20210101000000id_/https://portal.example/24"
        return FakeResponse(redirected, html)

    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(wayback.httpx2, "get", fake_get)
    assert wayback.ingest(PLACE, listing)[1] == []
    # Both external responses were landed, but a mismatched replay date yielded no dated evidence.
    assert len(listing["_documents"]) == 2
