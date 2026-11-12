"""The analyst compares actual offline reports, follows provenance and exports without a run."""

import csv

import pytest
from playwright.sync_api import Page, expect

from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.verticals.xray import run_xray
from tests.e2e.app import serve

pytestmark = pytest.mark.e2e


def seed_reports(tmp_path, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "CURSOR_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "documents"))
    store = Store(tmp_path / "store.json")
    gateway = build_gateway(store)
    for name, run_id in (
        ("demo", "xr-6f65393159"),
        ("kimberley-road", "xr-131a92ee3b"),
        ("charlemont-road", "xr-f20b9504d5"),
        ("sleaford-house", "xr-analyst-sleaford"),
    ):
        report = run_xray(gateway, name, offline=True).model_dump()
        report["run_id"] = run_id

        def save(data, report=report):
            data["xray_runs"][report["run_id"]] = report
            data["xray_places"][report["place_id"]] = report["run_id"]

        store.mutate(save)


@pytest.mark.parametrize("viewport", [(1280, 633), (390, 757)], ids=["desktop", "phone"])
def test_saved_comparison_sources_chart_and_all_csv(page: Page, tmp_path, monkeypatch, viewport):
    seed_reports(tmp_path, monkeypatch)
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    writes, errors = [], []
    page.on(
        "request", lambda request: writes.append(request.url) if request.method != "GET" else None
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    with serve(tmp_path, []) as base:
        page.goto(base + "/analyst")
        expect(page.locator("#analyst-status")).to_contain_text("4 of 4 saved reports ready")
        expect(page.locator("#analyst-rows > tr")).to_have_count(4)
        expect(page.locator("#analyst-chart > li")).to_have_count(4)
        row = page.locator('[data-listing="kimberley-road"]')
        expect(row).to_contain_text("81 m²")
        expect(row).to_contain_text("72 m²")
        expect(row).to_contain_text("63.1 m²")
        assert "energy-certificate" in row.get_by_role("link", name="72 m²").get_attribute("href")
        expect(page.locator('[data-listing="macquarie-way"] .analyst-score')).to_have_text("67")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="Download all as CSV").click()
        path = tmp_path / "all.csv"
        downloaded.value.save_as(path)
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert {row["run_id"] for row in rows} == {
            "xr-6f65393159",
            "xr-131a92ee3b",
            "xr-f20b9504d5",
            "xr-analyst-sleaford",
        }
        assert {row["kind"] for row in rows} == {"claim", "evidence", "finding"}
        assert any("energy-certificate" in row["url"] for row in rows)
        assert not writes, "comparison and exports must never start an analysis or paid request"
        assert not errors
        page.screenshot(path=str(tmp_path / f"analyst-{viewport[0]}.png"), full_page=True)


def test_gallery_failure_retry_and_partial_reports(page: Page, tmp_path, monkeypatch):
    seed_reports(tmp_path, monkeypatch)
    with serve(tmp_path, []) as base:
        page.route(
            "**/api/gallery", lambda route: route.fulfill(status=503, json={"error": "down"})
        )
        page.goto(base + "/analyst")
        expect(page.locator("#analyst-error")).to_contain_text("503")
        expect(page.get_by_role("button", name="Download all as CSV")).to_be_disabled()
        page.unroute("**/api/gallery")
        page.route(
            "**/api/xray/xr-131a92ee3b",
            lambda route: route.fulfill(status=503, json={"error": "down"}),
        )
        page.get_by_role("button", name="Reload saved reports").click()
        expect(page.locator("#analyst-status")).to_contain_text("3 of 4 saved reports ready")
        expect(page.locator('[data-listing="kimberley-road"]')).to_contain_text(
            "No saved report available"
        )
        expect(page.get_by_role("button", name="Download all as CSV")).to_be_enabled()
        page.unroute("**/api/xray/xr-131a92ee3b")
        page.get_by_role("button", name="Reload saved reports").click()
        expect(page.locator("#analyst-status")).to_contain_text("4 of 4 saved reports ready")
        page.route(
            "**/export.csv",
            lambda route: route.fulfill(status=200, content_type="text/html", body="unavailable"),
        )
        page.get_by_role("button", name="Download all as CSV").click()
        expect(page.locator("#analyst-error")).to_contain_text("did not return a CSV export")
        expect(page.get_by_role("button", name="Download all as CSV")).to_be_enabled()
