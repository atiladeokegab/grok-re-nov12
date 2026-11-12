import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import ROOT, serve

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("viewport", [(1280, 633), (390, 757)], ids=["desktop", "phone"])
def test_recorded_partner_scan_filters_without_network_effects(page: Page, tmp_path, viewport):
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    artifact = json.loads((ROOT / "starter/web/static/partner-scan.json").read_text())
    target = next(row for row in artifact["flags"] if row["check"] == "tenure")
    page.emulate_media(reduced_motion="reduce" if viewport[0] == 390 else "no-preference")
    writes = []
    page.on(
        "request", lambda request: writes.append(request.url) if request.method != "GET" else None
    )
    with serve(tmp_path, []) as base:
        page.goto(base + "/")
        entry = page.get_by_test_id("partner-scan-link")
        expect(entry).to_have_text("Ran across all 7,251 partner listings · 350 flagged for review")
        entry.click()
        assert page.url.endswith("/analyst#partner-scan")
        expect(page.locator("#partner-title")).to_have_text(
            "Ran across all 7,251 partner listings · flagged 350"
        )
        expect(page.locator("#partner-map circle")).to_have_count(artifact["rows_scanned"])
        expect(page.locator("#partner-map .is-flagged")).to_have_count(artifact["flagged_listings"])
        expect(page.locator("#partner-map svg")).to_have_attribute(
            "aria-label", re.compile("6,027.*1224")
        )
        expect(page.locator('#partner-title [data-count="7251"]')).to_have_text("7,251")
        expect(page.locator('#partner-title [data-count="350"]')).to_have_text("350")
        assert page.locator("#partner-map svg").bounding_box()["height"] > 250
        map_select = page.get_by_role("combobox", name="Explore a flagged listing")
        map_select.select_option(target["listing_id"])
        expect(page.locator(".partner-map-selection")).to_contain_text(target["address"])
        expect(page.locator(".partner-map-selection a")).to_have_attribute("href", target["url"])
        circle = page.locator("#partner-map .is-flagged").last
        circle.click()
        expect(map_select).to_have_value(circle.get_attribute("data-listing"))
        if viewport[0] == 390:
            assert (
                page.locator(".partner-map-region").first.evaluate(
                    "el => getComputedStyle(el).animationName"
                )
                == "none"
            )
        expect(page.locator("#partner-rows > tr")).to_have_count(5)
        page.locator("#partner-check").select_option("tenure")
        page.locator("#partner-search").fill(target["listing_id"])
        row = page.locator("#partner-rows > tr")
        expect(row).to_have_count(1)
        expect(row).to_contain_text(target["advert_value"])
        expect(row).to_contain_text(target["record_label"])
        expect(row.get_by_role("link")).to_have_attribute("href", target["url"])
        page.locator("#partner-search").fill("no listing could have this exact phrase")
        expect(page.locator("#partner-rows")).to_contain_text("No flagged comparisons match")
        page.get_by_text("What ran and what remains unverifiable").click()
        expect(page.locator("#partner-coverage")).to_contain_text("1,351 comparisons")
        expect(page.locator("#partner-missing")).to_contain_text("never flags")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not writes
        page.screenshot(path=str(tmp_path / f"partner-{viewport[0]}.png"), full_page=True)


def test_partner_scan_failure_can_be_retried(page: Page, tmp_path):
    with serve(tmp_path, []) as base:
        page.route(
            "**/static/partner-scan.json", lambda route: route.fulfill(status=503, body="down")
        )
        page.goto(base + "/analyst")
        expect(page.locator("#partner-error")).to_contain_text("503")
        expect(page.locator("#partner-results")).to_be_hidden()
        page.unroute("**/static/partner-scan.json")
        page.get_by_role("button", name="Reload partner scan").click()
        expect(page.locator("#partner-title")).to_contain_text("flagged 350")
        expect(page.locator("#partner-results")).to_be_visible()
