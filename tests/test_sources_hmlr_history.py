from starter.verticals.sources.hmlr_history import (
    ATTRIBUTION,
    _items,
    exact_address_match,
    parse_documents,
    parse_transactions,
)


def _record(*, paon="24", saon="", street="Macquarie Way", postcode="E14 3AU", date="2022-04-12"):
    return {
        "_about": "https://landregistry.data.gov.uk/data/ppi/transaction/example-id/current",
        "transactionId": "example-id",
        "transactionDate": date,
        "pricePaid": 475000,
        "estateType": "http://landregistry.data.gov.uk/def/ppi/F",
        "propertyType": "http://landregistry.data.gov.uk/def/ppi/F",
        "propertyAddress": {
            "paon": paon,
            "saon": saon,
            "street": street,
            "postcode": postcode,
        },
    }


def test_parses_exact_sale_history_without_converting_basis_or_currency():
    older = _record(date="2017-03-01", saon="Flat 2")
    newer = _record(date="2022-04-12", saon="Flat 2")
    rows = parse_transactions(
        {"_embedded": {"item": [newer, older]}},
        "Flat 2, 24 Macquarie Way",
        "E14 3AU",
    )

    assert [row["transaction_date"] for row in rows] == ["2017-03-01", "2022-04-12"]
    assert rows[0]["price"] == 475000
    assert rows[0]["currency"] == "GBP"
    assert rows[0]["price_basis"] == "achieved sale price"
    assert rows[0]["tenure"] == "Freehold"
    assert rows[0]["property_type"] == "Flat/maisonette"
    assert rows[0]["source_url"].startswith("https://landregistry.data.gov.uk/")
    assert ATTRIBUTION.startswith("Contains HM Land Registry data")


def test_address_mismatch_and_missing_unit_never_create_evidence():
    flat = _record(saon="Flat 2")
    wrong_paon = _record(paon="26", saon="Flat 2")
    wrong_street = _record(saon="Flat 2", street="Macquarie Road")
    wrong_postcode = _record(saon="Flat 2", postcode="E14 3AB")

    assert exact_address_match(flat, "Flat 2, 24 Macquarie Way", "E14 3AU")
    assert not exact_address_match(flat, "24 Macquarie Way", "E14 3AU")
    assert not exact_address_match(wrong_paon, "Flat 2, 24 Macquarie Way", "E14 3AU")
    assert not exact_address_match(wrong_street, "Flat 2, 24 Macquarie Way", "E14 3AU")
    assert not exact_address_match(wrong_postcode, "Flat 2, 24 Macquarie Way", "E14 3AU")
    assert parse_transactions({"_embedded": {"item": [flat]}}, "24 Macquarie Way", "E14 3AU") == []


def test_accepts_punctuation_and_case_normalization_but_not_partial_building_match():
    exact = _record(paon="Rose Cottage", street="King's Road")
    partial = _record(paon="Rose", street="King's Road")

    assert exact_address_match(exact, "Rose Cottage, King's Road", "e14 3au")
    assert not exact_address_match(partial, "Rose Cottage, King's Road", "E14 3AU")


def test_missing_or_malformed_transactions_are_not_negative_property_evidence():
    assert parse_transactions({}, "24 Macquarie Way", "E14 3AU") == []
    bad = _record(date="not-a-date")
    assert parse_transactions({"_embedded": {"item": [bad]}}, "24 Macquarie Way", "E14 3AU") == []


def test_actual_elda_result_items_and_locality_suffix_parse_exactly():
    import json

    row = {
        "_about": "http://landregistry.data.gov.uk/data/ppi/transaction/id-17/current",
        "transactionId": "id-17",
        "transactionDate": "Wed, 30 Jul 1997",
        "pricePaid": 243000,
        "estateType": {
            "_about": "http://landregistry.data.gov.uk/def/common/leasehold",
            "label": [{"_value": "Leasehold"}],
        },
        "propertyType": {
            "_about": "http://landregistry.data.gov.uk/def/common/flat-maisonette",
            "label": [{"_value": "Flat-maisonette"}],
        },
        "propertyAddress": {
            "paon": "BUILDING 17",
            "saon": "FLAT 3",
            "street": "TEST ROAD",
            "postcode": "AB1 2CD",
            "locality": "EXAMPLE TOWN",
        },
    }
    payload = {"format": "linked-data-api", "result": {"items": [row]}}
    content = json.dumps(payload, indent=2).encode()
    docs = [
        {"url": "https://landregistry.data.gov.uk/query", "content": content, "payload": payload}
    ]

    records = parse_documents(docs, "Lot 8 Flat 3, Building 17, Test Road, Example Town", "AB1 2CD")

    assert len(records) == 1
    assert records[0]["price"] == 243000
    assert records[0]["transaction_date"] == "1997-07-30"
    assert records[0]["tenure"] == "Leasehold"
    assert records[0]["property_type"] == "Flat/maisonette"
    assert (
        records[0]["source_url"]
        == "https://landregistry.data.gov.uk/data/ppi/transaction/id-17/current"
    )
    assert records[0]["doc_quote"] in content.decode()


def test_unrecognized_address_shapes_and_nonwhole_pound_prices_abstain():
    from starter.verticals.sources.hmlr_history import _source_url

    assert not exact_address_match(_record(), "24 Macquarie Way Building", "E14 3AU")
    fractional = _record()
    fractional["pricePaid"] = "475000.50"
    assert (
        parse_transactions({"result": {"items": [fractional]}}, "24 Macquarie Way", "E14 3AU") == []
    )
    assert _source_url("javascript:alert(1)") is None
    assert _source_url("https://evil.example/data/ppi/transaction/x") is None
    assert _source_url("https://landregistry.data.gov.uk:bad/data/ppi/transaction/x") is None
    assert _items({"result": {"different": []}}) is None
    invalid_uri = _record()
    invalid_uri["_about"] = "https://evil.example/data/ppi/transaction/fake/current"
    assert (
        parse_transactions({"result": {"items": [invalid_uri]}}, "24 Macquarie Way", "E14 3AU")
        == []
    )


def test_ingest_lands_original_json_and_grounds_history_in_document_text(tmp_path, monkeypatch):
    import hashlib
    import json

    from starter.core.ingest import decoded_text, raw_bytes
    from starter.core.xray import Place
    from starter.verticals.sources import hmlr_history

    row = _record(saon="")
    payload = {"result": {"items": [row]}}
    raw = json.dumps(payload, indent=2).encode()
    url = "https://landregistry.data.gov.uk/data/ppi/transaction-record.json?postcode=AB1+2CD"
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(
        hmlr_history,
        "collect",
        lambda address, postcode: ([{"url": url, "content": raw, "payload": payload}], url),
    )
    listing = {"offline": False, "listing_id": "invented-123"}
    place = Place(id="invented-place", address="24 Macquarie Way", postcode="E14 3AU")

    _, evidence = hmlr_history.ingest(place, listing)

    assert {item.field for item in evidence} == {"sale_price_gbp", "tenure", "property_type"}
    assert all(item.observed_at == "2022-04-12" for item in evidence)
    assert all(item.document_id == listing["_documents"][0].id for item in evidence)
    assert all(item.unit == "GBP" for item in evidence if item.field == "sale_price_gbp")
    doc = listing["_documents"][0]
    assert raw_bytes(doc) == raw
    assert doc.sha256 == hashlib.sha256(raw).hexdigest()
    text = decoded_text(doc)
    assert all(text[item.span.start : item.span.end] == item.span.quote for item in evidence)
    assert all(item.doc_span == item.span.quote for item in evidence)
