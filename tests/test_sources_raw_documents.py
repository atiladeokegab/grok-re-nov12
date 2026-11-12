from starter.core.ingest import raw_bytes
from starter.core.xray import Place
from starter.verticals.sources import epc, listing_history


def test_advert_keeps_original_html_before_extracting_text(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    original = "<h1>24 Example Street</h1><p>Sold £500,000</p>"
    monkeypatch.setattr(listing_history, "get_text", lambda url: original)
    listing = {"offline": False, "url": "https://www.auctionhouse.co.uk/example"}
    page = listing_history._page(listing)
    [document] = listing["_documents"]
    assert raw_bytes(document) == original.encode()
    assert page["text"] == "24 Example Street Sold £500,000"
    assert document.url == listing["url"]


def test_epc_keeps_search_and_original_certificate(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    path = "/energy-certificate/example-cert"
    search = f'<tr><td>24 Example Street, London, E1 1AA</td><a href="{path}">D</a></tr>'
    certificate = "<h1>24 Example Street</h1><p>energy rating is D</p>"
    monkeypatch.setattr(
        epc, "get_text", lambda url, params=None: certificate if url.endswith(path) else search
    )
    place = Place(id="example", address="24 Example Street, London, E1 1AA", postcode="E1 1AA")
    listing = {"offline": False, "listing_id": "example"}
    _, evidence = epc.ingest(place, listing)
    documents = listing["_documents"]
    assert len(documents) == 2
    assert raw_bytes(documents[1]) == certificate.encode()
    assert documents[1].url == evidence[0].source_url
