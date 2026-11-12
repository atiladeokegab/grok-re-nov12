from starter.verticals.sources import listing_history


def test_live_page_collects_only_ordered_lot_gallery_images(monkeypatch):
    html = """
    <img alt="Lot Image" src="/lot-image/930671?w=670">
    <a href="/energy-certificate/123">EPC certificate</a>
    <img alt="Floorplan" src="/lot-image/999999?w=670">
    <img alt="Lot Image" src="/lot-image/930672?w=670">
    <img alt="Lot Image" src="/lot-image/930671?w=1200">
    <img alt="Lot Image" src="https://www.auctionhouse.co.uk/lot-image/930673?size=large">
    """
    monkeypatch.setattr(listing_history, "get_text", lambda url: html)
    monkeypatch.setattr(listing_history, "now", lambda: "2026-11-12T00:00:00Z")
    monkeypatch.setattr(listing_history, "visible_text", lambda text: "listing text")

    page = listing_history._page({"offline": False, "url": "https://www.auctionhouse.co.uk/lot/1"})

    assert page["photos"] == [
        "https://www.auctionhouse.co.uk/lot-image/930671",
        "https://www.auctionhouse.co.uk/lot-image/930672",
        "https://www.auctionhouse.co.uk/lot-image/930673",
    ]
    assert page["text"] == "listing text"
