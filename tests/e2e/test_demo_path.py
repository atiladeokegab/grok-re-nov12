"""The live demo's path (hub demo-script.md) in a real browser, offline: the demo listing scores 67,
the three spoken findings, the Property type evidence with its highlighted quote, the Time machine,
the "Try these" gallery and the lease beat. If this fails, the demo is broken. Run by `make e2e`."""

import zipfile

import pytest
from playwright.sync_api import Page, expect

from starter.web.test_analyst_page import seed_reports
from tests.e2e.app import serve, stub_fonts

pytestmark = pytest.mark.e2e
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("demo-server")
    with pytest.MonkeyPatch.context() as monkeypatch:
        seed_reports(tmp, monkeypatch)
        with serve(tmp, []) as base:
            yield base


@pytest.fixture
def errors(page: Page) -> list[str]:
    found: list[str] = []
    page.on("console", lambda m: found.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: found.append(str(e)))
    stub_fonts(page)
    return found


def test_demo_listing_walkthrough(page: Page, server, errors):
    page.goto(server + "/")
    expect(page.locator("#gallery li")).to_have_count(4)

    page.locator(".gallery-item").first.click()
    expect(page.get_by_test_id("trust-score")).to_have_text("67", timeout=30_000)

    findings = page.get_by_test_id("finding")
    expect(findings.filter(has_text="Energy rating")).to_contain_text("Matches the record")
    expect(findings.filter(has_text="Tenure")).to_contain_text("Could not verify")
    expect(findings.filter(has_text="Property type")).to_contain_text("Doesn’t match the record")

    findings.filter(has_text="Property type").click()
    detail = page.get_by_test_id("finding-detail")
    expect(detail.locator(".comparison")).to_contain_text("Semi-Detached")
    expect(detail.locator(".comparison")).to_contain_text("End-terrace house")
    expect(detail.locator("pre.trace-document mark").first).to_be_visible()

    page.get_by_role("button", name="Time machine").click()
    expect(page.locator("#history-timeline .timeline-event").first).to_be_visible()
    assert errors == []


def test_lease_field_shows_its_clause(page: Page, server, errors, tmp_path):
    lease = tmp_path / "lease.docx"  # a two-paragraph lease built here: no sample data in the repo
    paras = ["“Main Rent”", "the yearly rent of fifty thousand pounds (£50,000);"]
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(lease, "w") as z:
        z.writestr(
            "word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        )

    page.goto(server + "/lease")
    page.set_input_files("#lease-file", lease)
    page.click("#lease-submit")
    expect(page.locator("[data-field=main_rent] blockquote")).to_contain_text(
        "yearly rent of fifty"
    )
    assert errors == []
