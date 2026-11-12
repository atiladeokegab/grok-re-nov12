"""The SSE completion race must not let a stale running snapshot win over the final report."""

import json

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.app import serve

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("viewport", [(1280, 633), (390, 757)], ids=["desktop", "phone"])
def test_done_event_waits_for_inflight_refresh_then_loads_terminal_report(
    page: Page, tmp_path, viewport
):
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script("""
      class TestEventSource extends EventTarget {
        constructor(url) {
          super(); this.url = url; this.closed = false; window.__xrayEvents = this;
        }
        close() { this.closed = true; }
        emit(type, data) {
          this.dispatchEvent(new MessageEvent(type, {data: JSON.stringify(data)}));
        }
        addEventListener(type, listener, options) {
          if (type !== 'done') return super.addEventListener(type, listener, options);
          return super.addEventListener(type, async event => {
            window.__doneHandlerStarted = true;
            try { await listener.call(this, event); }
            finally { window.__doneHandlerSettled = true; }
          }, options);
        }
      }
      window.EventSource = TestEventSource;
    """)
    gets = 0
    held = []
    with serve(tmp_path, []) as base:

        def api(route):
            nonlocal gets
            request = route.request
            if request.method == "POST" and request.url.endswith("/api/xray"):
                route.fulfill(
                    status=202,
                    content_type="application/json",
                    body=json.dumps({"run_id": "run-race"}),
                )
            elif request.method == "GET" and request.url.endswith("/api/xray/run-race"):
                gets += 1
                if gets == 2:
                    held.append(route)
                else:
                    done = gets >= 3
                    route.fulfill(
                        content_type="application/json",
                        body=json.dumps(report("done", 67) if done else report("running", 0)),
                    )
            else:
                route.continue_()

        page.route("**/api/xray**", api)
        page.goto(base)
        page.get_by_test_id("listing-input").fill("fixture-race")
        page.get_by_test_id("xray-submit").click()
        expect(page.get_by_test_id("trust-score")).to_have_text("0")
        page.wait_for_function("window.__xrayEvents !== undefined")
        with page.expect_request("**/api/xray/run-race", timeout=5000) as second_get:
            page.evaluate("window.__xrayEvents.emit('finding', {finding_id: 'finding-area'})")
        assert second_get.value.method == "GET"
        page.wait_for_function("window.__xrayEvents && window.__xrayEvents.url.includes('/events')")
        page.wait_for_function(
            "document.querySelector('#run-id')?.textContent.includes('run-race')"
        )
        assert held, "finding event should start the second GET, held until the done event arrives"

        page.evaluate("window.__xrayEvents.emit('done', {status: 'done'})")
        page.wait_for_function("window.__doneHandlerStarted === true")
        expect(page.locator("#run-status")).not_to_have_text("Check complete.")
        assert not page.evaluate("window.__doneHandlerSettled === true"), (
            "done handler must wait for the in-flight GET"
        )

        held.pop().fulfill(
            content_type="application/json",
            body=json.dumps(report("running", 0)),
        )
        expect(page.get_by_test_id("trust-score")).to_have_text("67", timeout=10000)
        assert gets == 3, "the stale running snapshot must be followed by a fresh terminal GET"
        expect(page.locator("#run-status")).to_have_text("Check complete.")
        expect(page.get_by_test_id("finding")).to_have_count(4)
        expect(page.locator("#sources")).to_contain_text("companies_house")
        expect(page.locator("#sources")).to_contain_text("Not enabled for this check")
        expect(page.locator("#error")).to_be_hidden()
        assert page.evaluate("window.__xrayEvents.closed")


def report(status, trust_score):
    findings = (
        [
            {
                "id": f"finding-{field}",
                "field": field,
                "verdict": "unverifiable",
                "evidence_ids": [],
            }
            for field in ("floor_area", "energy_rating", "tenure", "property_type")
        ]
        if status == "done"
        else []
    )
    return {
        "run_id": "run-race",
        "listing_id": "fixture-race",
        "place_id": "place-race",
        "status": status,
        "trust_score": trust_score,
        "place": {
            "id": "place-race",
            "title": "Controlled SSE race fixture",
            "address": "Synthetic",
        },
        "counts": {"matches": 0, "disagrees": 0, "unverifiable": 0, "flag": 0},
        "findings": findings,
        "claims": [],
        "evidence": [],
        "history": [],
        "sources": [{"name": "companies_house", "status": "off", "n_evidence": 0}]
        if findings
        else [],
        "client_calls": {},
    }
