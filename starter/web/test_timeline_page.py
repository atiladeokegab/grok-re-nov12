"""Time-machine containers must not turn their empty text argument into a visible 'null'."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import serve

pytestmark = pytest.mark.e2e


def test_time_machine_renders_records_without_null_container_labels(page: Page, tmp_path):
    with serve(tmp_path, []) as base:
        page.goto(base + "/lease")
        page.evaluate("""async () => {
          const { renderTimeline } = await import('/static/timeline.js');
          const container = document.createElement('div');
          container.id = 'timeline-regression'; document.body.append(container);
          renderTimeline(container, { history: [{
            field: 'price', value: 770000, unit: 'GBP', source_name: 'Recorded advert',
            source_url: 'https://records.test/advert', fetched_at: '2026-10-24T10:00:00Z',
          }] });
        }""")
        timeline = page.locator("#timeline-regression")
        expect(timeline).to_contain_text("2026")
        expect(timeline).to_contain_text("770000 GBP")
        assert "null" not in timeline.inner_text()
        timeline.get_by_role("button").click()
        expect(timeline.get_by_role("link", name="Open source")).to_be_visible()
        expect(timeline).to_contain_text("Recorded advert")
