"""Exercise the lease page against real extraction, plus upload and evaluation failures."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import serve
from tests.test_lease import docx

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("viewport", [(1280, 633), (390, 757)], ids=["desktop", "phone"])
def test_lease_upload_shows_sourced_terms_and_recorded_evaluation(page: Page, tmp_path, viewport):
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.emulate_media(reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    path = docx(tmp_path / "office-lease.docx")
    with serve(tmp_path, []) as base:
        page.goto(base + "/lease")
        expect(page.locator("#benchmark-strict")).to_have_text("69 / 80")
        expect(page.locator("#benchmark-content")).to_have_text("74 / 80")
        expect(page.locator("#lease-submit")).to_be_disabled()
        page.locator("#lease-file").set_input_files(path)
        page.get_by_role("button", name="Read this lease").click()
        expect(page.locator("#lease-results")).to_be_visible()
        expect(page.locator("#lease-filename")).to_have_text("office-lease.docx")
        expect(page.locator(".lease-term")).to_have_count(10)
        rent = page.locator('[data-field="main_rent"]')
        expect(rent.locator("summary")).to_contain_text("Placeholder")
        expect(rent.locator("blockquote")).to_contain_text("[AMOUNT IN WORDS]")
        expect(rent).to_contain_text("Source: definition “Main Rent”")
        expect(page.locator('[data-field="insurance"] summary')).to_contain_text("Not found")
        page.locator('[data-field="break_clause"] summary').click()
        expect(page.locator('[data-field="break_clause"]')).to_contain_text("Optional clause")
        expect(page.locator("#lease-error")).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors


def test_lease_errors_are_recoverable_and_do_not_show_a_previous_report(page: Page, tmp_path):
    with serve(tmp_path, []) as base:
        page.route(
            "**/api/lease/eval",
            lambda route: route.fulfill(status=503, json={"error": "Evaluation temporarily down"}),
        )
        page.goto(base + "/lease")
        expect(page.locator("#benchmark-status")).to_contain_text("Evaluation temporarily down")
        page.unroute("**/api/lease/eval")
        page.get_by_role("button", name="Retry evaluation").click()
        expect(page.locator("#benchmark-strict")).to_have_text("69 / 80")
        page.locator("#lease-file").set_input_files(
            {"name": "office.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.7"}
        )
        page.get_by_role("button", name="Read this lease").click()
        expect(page.locator("#lease-error")).to_contain_text("Choose a Word document")
        page.locator("#lease-file").set_input_files(
            {"name": "large.docx", "mimeType": "application/octet-stream", "buffer": b"x" * 5242881}
        )
        page.get_by_role("button", name="Read this lease").click()
        expect(page.locator("#lease-error")).to_contain_text("too large")
        page.locator("#lease-file").set_input_files(
            {"name": "broken.docx", "mimeType": "application/octet-stream", "buffer": b"broken"}
        )
        page.get_by_role("button", name="Read this lease").click()
        expect(page.locator("#lease-error")).to_contain_text("not a readable .docx")
        expect(page.locator("#lease-results")).to_be_hidden()
        page.locator("#lease-file").set_input_files(docx(tmp_path / "good.docx"))
        page.get_by_role("button", name="Read this lease").click()
        expect(page.locator("#lease-results")).to_be_visible()
        expect(page.locator("#lease-error")).to_be_hidden()
