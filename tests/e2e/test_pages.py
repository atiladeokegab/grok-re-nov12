"""The pages in a real browser: the app started the way `make dev` starts it (offline, seeded), two
sample cases run through the API, then Chromium checks what a judge would see. Run by `make e2e`
only; `make check` deselects the e2e marker, so it never needs a browser."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import serve, stub_fonts

pytestmark = pytest.mark.e2e
CASES = ["001", "002"]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """The app on a free port, offline, with CASES already run; yields its base URL."""
    with serve(tmp_path_factory.mktemp("e2e-server"), CASES) as base:
        yield base


@pytest.fixture
def errors(page: Page) -> list[str]:
    """Console errors and uncaught exceptions on the page. Web fonts are stubbed so the test is
    offline and a missing network is not a console error."""
    found: list[str] = []
    page.on("console", lambda m: found.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: found.append(str(e)))
    stub_fonts(page)
    return found


@pytest.fixture
def shots(tmp_path) -> Path:
    """Where screenshots go: $E2E_OUT (make e2e prints it), else this test's tmp dir."""
    out = Path(os.environ.get("E2E_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def test_runs_page_shows_every_run(page: Page, server, errors, shots):
    page.goto(server + "/runs")
    expect(page.get_by_role("heading", name="Runs", exact=True)).to_be_visible()
    for case in CASES:
        card = page.locator("[data-run]", has_text=f"Case {case}")
        expect(card).to_contain_text("DONE")
        expect(card).to_contain_text("acknowledged the case")
        expect(card).to_contain_text("send_message")
        expect(card).to_contain_text("SIMULATED")
    page.screenshot(path=shots / "runs.png", full_page=True)
    assert errors == []


def test_one_case_filtered_shows_only_its_run(page: Page, server, errors, shots):
    page.goto(server + "/runs")
    page.get_by_label("Filter runs").fill("Case 001")
    expect(page.locator("[data-run]", has_text="Case 001")).to_be_visible()
    expect(page.locator("[data-run]", has_text="Case 002")).to_be_hidden()
    expect(page.locator("[data-run]", has_text="Case 001")).to_contain_text("DONE")
    page.screenshot(path=shots / "case-001.png", full_page=True)
    assert errors == []
