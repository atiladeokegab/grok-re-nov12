"""The pages in a real browser: the app started the way `make dev` starts it (offline), then
Chromium checks what a judge would see. Run by `make e2e`
only; `make check` deselects the e2e marker, so it never needs a browser."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import serve, stub_fonts

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """The app on a free port, offline; yields its base URL."""
    with serve(tmp_path_factory.mktemp("e2e-server"), []) as base:
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


def test_runs_page_renders_without_errors(page: Page, server, errors, shots):
    page.goto(server + "/runs")
    expect(page.get_by_role("heading", name="Runs", exact=True)).to_be_visible()
    expect(page.get_by_text("No runs yet")).to_be_visible()
    page.screenshot(path=shots / "runs.png", full_page=True)
    assert errors == []


def test_a_finished_run_opens_by_link_and_survives_a_reload(page: Page, server, errors, shots):
    """The demo fallback: /?run=<id> shows the saved run as it finished; nothing new runs."""
    api = page.request
    run_id = api.post(server + "/api/xray", data={"listing_id": "demo", "offline": True}).json()[
        "run_id"
    ]
    for _ in range(100):
        if api.get(f"{server}/api/xray/{run_id}").json()["status"] != "running":
            break
        page.wait_for_timeout(100)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(f"{server}/?run={run_id}")
    for reload in (False, True):
        if reload:
            page.reload()
        expect(page.locator("#run-id")).to_have_text(f"Run {run_id}")
        expect(page.locator("#score")).not_to_have_text("—")
        expect(page.get_by_test_id("finding").first).to_be_visible()
    page.get_by_role("button", name="Property type").click()
    expect(page.locator("#finding-detail")).to_be_visible()
    page.locator('[data-view="timeline"]').click()
    expect(page.locator("#history-timeline")).to_be_visible()
    page.screenshot(path=shots / "run-link.png", full_page=True)
    assert posts == [] and errors == []
    page.goto(server + "/?run=xr-nope")
    expect(page.locator("#error")).to_contain_text('No X-ray run "xr-nope"')


def test_starting_a_run_puts_its_link_in_the_url(page: Page, server, errors):
    page.goto(server + "/")
    page.locator(".gallery-item").first.click()  # gallery runs are offline fixtures
    expect(page.locator("#run-id")).to_have_text(re.compile(r"^Run xr-"))
    run_id = page.locator("#run-id").inner_text().removeprefix("Run ")
    assert page.url.endswith(f"/?run={run_id}")
    assert errors == []
