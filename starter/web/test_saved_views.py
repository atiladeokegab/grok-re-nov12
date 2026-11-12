"""Saved reports expose their detail views and navigation without starting another check."""

from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from starter.web.test_analyst_page import seed_reports
from tests.e2e.app import serve

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("viewport", [(1280, 633), (390, 757)], ids=["desktop", "phone"])
def test_saved_views_fit_and_request_the_saved_graph(page: Page, tmp_path, monkeypatch, viewport):
    seed_reports(tmp_path, monkeypatch)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    posts, graph_queries, errors = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def record(request):
        if request.method != "GET":
            posts.append(request.url)
        if urlparse(request.url).path.endswith("/graph"):
            graph_queries.append(parse_qs(urlparse(request.url).query))

    page.on("request", record)
    with serve(tmp_path, []) as base:
        page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(base + "/") and route.request.method == "GET"
                else route.abort()
            ),
        )
        page.goto(base + "/?run=xr-131a92ee3b")
        expect(page.locator("#place-title")).to_have_text("24 Kimberley Road, Brighton, BN2 4EP")
        expect(page.get_by_role("link", name="Analyst", exact=True)).to_have_attribute(
            "href", "/analyst"
        )
        expect(page.get_by_role("link", name="Lease review", exact=True)).to_have_attribute(
            "href", "/lease"
        )
        expect(page.locator("#history-count")).to_have_text("5 records")
        expect(page.locator(".history-earlier")).to_contain_text("872 sq ft")
        assert page.locator("#history del").count() == 0
        if viewport[0] == 1280:
            assert page.locator("#score").bounding_box()["y"] < 400
        for view, heading in (
            ("inside", "inside-title"),
            ("connections", "connections-title"),
            ("timeline", "timeline-title"),
        ):
            page.locator(f'[data-view="{view}"]').click()
            expect(page.locator(f"#{view}-view")).to_be_visible()
            assert page.locator(f"#{heading}").bounding_box()["y"] < 130
        assert graph_queries == [{"run_id": ["xr-131a92ee3b"]}]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not posts and not errors
        page.screenshot(path=str(tmp_path / f"saved-view-{viewport[0]}.png"))
