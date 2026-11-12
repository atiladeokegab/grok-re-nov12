from starter.core.ingest import decoded_text, raw_bytes
from starter.core.xray import Place
from starter.verticals.sources import epc_history
from starter.verticals.sources.epc_history import collect_history, match_row, parse_certificate

ADDRESS = "Flat 2, 12 Oak House, High Street, London, AA1 1AA"


def certificate(address=ADDRESS, assessed="1 February 2020", lodged="3 February 2020", rating="D"):
    dates = f"Date of assessment {assessed}" if assessed else ""
    dates += f" Date of registration {lodged}" if lodged else ""
    return (
        f"Address {address} Energy rating is {rating} Property type Flat Total floor area "
        f"84 square metres {dates} Valid until 1 January 2010"
    )


def test_certificates_are_exact_address_and_oldest_first():
    rows = collect_history(
        [
            ("https://epc.example/new", certificate(assessed="1 March 2024", rating="C")),
            ("https://epc.example/old", certificate(assessed="1 February 2020", rating="D")),
        ],
        ADDRESS,
    )

    assert [row["assessment_date"] for row in rows] == ["2020-02-01", "2024-03-01"]
    assert [row["fields"]["energy_rating"]["value"] for row in rows] == ["D", "C"]
    assert rows[0]["lodgement_date"] == "2020-02-03"
    assert rows[0]["source_url"] == "https://epc.example/old"


def test_valid_until_is_not_used_as_history_date():
    assert (
        parse_certificate(
            certificate(assessed="", lodged=""), "https://epc.example/undated", ADDRESS
        )
        is None
    )


def test_missing_or_wrong_exact_address_is_not_history():
    assert (
        parse_certificate(
            certificate(address="Flat 3, 12 Oak House, High Street, AA1 1AA"),
            "https://epc.example/other-flat",
            ADDRESS,
        )
        is None
    )
    assert (
        parse_certificate(
            certificate(address="Flat 2, 12 Pine House, High Street, AA1 1AA"),
            "https://epc.example/other-building",
            ADDRESS,
        )
        is None
    )
    assert (
        parse_certificate(
            certificate(address="12 Oak House, High Street, AA1 1AA"),
            "https://epc.example/whole-house",
            ADDRESS,
        )
        is None
    )


def test_search_row_must_match_the_full_building_and_street():
    rows = [
        "Flat 2, 12 Oak House, High Street, London, AA1 1AA | /energy-certificate/oak",
        "Flat 2, 12 Pine House, High Road, London, AA1 1AA | /energy-certificate/pine",
    ]
    assert match_row(rows, ADDRESS) == "/energy-certificate/oak"
    assert match_row(rows, "Flat 2, 12 Pine House, High Road, London, AA1 1AA") == (
        "/energy-certificate/pine"
    )
    assert match_row(rows, "Flat 2, 12 Oak Homes, High Street, London, AA1 1AA") is None


def test_exact_street_and_postcode_allow_register_to_omit_locality():
    rows = ["24, Macquarie Way, LONDON, E14 3AU | /energy-certificate/macquarie"]
    assert match_row(rows, "24 Macquarie Way, Isle of Dogs, London, E14 3AU") == (
        "/energy-certificate/macquarie"
    )


def test_expired_certificate_remains_valid_historical_evidence():
    row = parse_certificate(
        certificate(assessed="1 January 2009", lodged="", rating="G"),
        "https://epc.example/expired",
        ADDRESS,
    )
    assert row["assessment_date"] == "2009-01-01"
    assert row["fields"]["energy_rating"]["value"] == "G"
    assert row["observed_at"] == "2009-01-01"


def test_live_page_layout_without_address_heading_and_certificate_date():
    page = (
        "24, Macquarie Way LONDON E14 3AU Energy rating D "
        "Property type End-terrace house Total floor area 84 square metres "
        "Date of assessment 29 February 2020 Date of certificate 3 March 2020 "
        "Valid until 2 March 2030"
    )
    record = parse_certificate(
        page, "https://epc.example/actual-layout", "24 Macquarie Way London E14 3AU"
    )

    assert record["assessment_date"] == "2020-02-29"
    assert record["certificate_date"] == "2020-03-03"
    assert record["fields"]["energy_rating"]["value"] == "D"
    assert record["fields"]["floor_area_m2"]["value"] == 84.0


def test_ingest_lands_original_html_and_emits_dated_grounded_scalar_evidence(monkeypatch, tmp_path):
    raw = """<p class="epc-address">24, Macquarie Way<br>LONDON E14 3AU</p>
    <p>Energy rating D</p><p>Property type End-terrace house</p>
    <p>Total floor area 84 square metres</p>
    <dt>Date of assessment</dt><dd>29 February 2020</dd>
    <dt>Date of certificate</dt><dd>3 March 2020</dd>
    <p>Valid until 2 March 2030</p>"""
    url = "https://find-energy-certificate.service.gov.uk/energy-certificate/123"
    listing = {
        "offline": True,
        "listing_id": "fixture",
        "fixture": {"epc_history": {"documents": [(url, raw)]}},
    }
    place = Place(
        id="place",
        address="24 Macquarie Way, Isle of Dogs, London, E14 3AU",
        postcode="E14 3AU",
    )
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))

    _, evidence = epc_history.ingest(place, listing)

    assert {item.field for item in evidence} == {
        "energy_rating",
        "property_type",
        "floor_area_m2",
    }
    assert all(item.observed_at == "2020-02-29" for item in evidence)
    assert all(item.document_id == listing["_documents"][0].id for item in evidence)
    document = listing["_documents"][0]
    assert raw_bytes(document) == raw.encode()
    text = decoded_text(document)
    assert all(text[item.span.start : item.span.end] == item.span.quote for item in evidence)
    assert "Valid until" not in " ".join(item.doc_span for item in evidence)


def test_live_collector_follows_previous_certificate_and_keeps_original_html(monkeypatch):
    current_url = "https://find-energy-certificate.service.gov.uk/energy-certificate/current"
    old_url = "https://find-energy-certificate.service.gov.uk/energy-certificate/old"
    search_html = (
        "<table><tr><td>24, Macquarie Way, LONDON, E14 3AU</td>"
        '<td><a href="/energy-certificate/current">Current certificate</a></td></tr></table>'
    )
    current_html = (
        '<p class="epc-address">24, Macquarie Way<br>LONDON E14 3AU</p>'
        '<a href="/energy-certificate/old">Previous certificate</a>'
    )
    old_html = '<p class="epc-address">24, Macquarie Way<br>LONDON E14 3AU</p>'
    pages = {current_url: current_html, old_url: old_html}

    def fake_get_text(url, params=None):
        return search_html if params else pages[url]

    monkeypatch.setattr(epc_history, "get_text", fake_get_text)
    place = Place(
        id="place",
        address="24 Macquarie Way, Isle of Dogs, London, E14 3AU",
        postcode="E14 3AU",
    )

    documents = list(epc_history._live_documents(place))

    assert [url for url, _ in documents] == [
        f"{epc_history.BASE}/find-a-certificate/search-by-postcode?postcode=E14+3AU",
        current_url,
        old_url,
    ]
    assert documents[1][1] == current_html
    assert documents[2][1] == old_html


def test_live_collector_still_yields_search_document_when_no_exact_row(monkeypatch):
    search_html = "<table><tr><td>24 Macquarie Way E14 3AU</td></tr></table>"
    monkeypatch.setattr(epc_history, "get_text", lambda *args, **kwargs: search_html)
    place = Place(
        id="place",
        address="Flat 2, 24 Macquarie Way, London, E14 3AU",
        postcode="E14 3AU",
    )

    assert list(epc_history._live_documents(place)) == [
        (
            f"{epc_history.BASE}/find-a-certificate/search-by-postcode?postcode=E14+3AU",
            search_html,
        )
    ]
