"""A case's time budget stops work: no tool runs and nothing is written once a case is cancelled
or out of time, and the Claude loop stops before a model call it has no time for."""

import json
import threading
import time

import anthropic
import httpx2
import pytest

from starter.agent.loop import ClaudeProvider, run
from starter.core.errors import CaseCancelled
from starter.core.gateway import build_gateway
from starter.runtime.config import Settings

CASE = {"id": "b-1", "body": "Help."}


def tool_calls(store) -> list[dict]:
    return [e for e in store.snapshot()["events"] if e["type"] == "tool_call"]


def test_iterations_and_effort_are_settings():
    s = Settings.from_env({})
    assert (s.max_iterations, s.effort) == (8, "medium")
    s = Settings.from_env({"MAX_ITERATIONS": "3", "EFFORT": "high"})
    assert (s.max_iterations, s.effort) == (3, "high")
    with pytest.raises(ValueError, match="EFFORT must be one of"):
        Settings.from_env({"EFFORT": "extreme"})


def test_a_cancelled_case_reaches_no_tool_and_writes_nothing(store):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CaseCancelled):
        build_gateway(store).call("get_skill", {"name": "escalation"}, "c1", cancel)
    assert tool_calls(store) == []


def test_a_late_tool_call_after_cancel_is_refused(store):
    cancel = threading.Event()

    class Late:
        """Stands in for a case the runner gave up on, whose thread then tries to act."""

        name = "test"

        def run(self, system, messages, tools, trace, seconds_left):
            cancel.set()
            send = next(t for t in tools if t.name == "send_message")
            send.call({"to": "ann", "body": "too late"})
            return "Sent.\nSTATE: DONE", ""

    result = run(CASE, build_gateway(store), Settings(), Late(), cancel=cancel)
    assert result.final_state == "ERROR"
    assert result.trace[-1]["error"] == "CaseCancelled: case cancelled"
    assert result.actions == [] and tool_calls(store) == []


def endless_claude(settings: Settings, delay: float):
    """A ClaudeProvider whose API asks for get_skill forever, each reply taking `delay`."""
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append({**json.loads(request.content), "timeout": request.extensions["timeout"]})
        time.sleep(delay)
        use = {
            "type": "tool_use",
            "id": f"tu_{len(requests)}",
            "name": "get_skill",
            "input": {"name": "escalation"},
        }
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [use],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider = ClaudeProvider(settings)
    provider.client = anthropic.Anthropic(
        api_key="k",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return provider, requests


def test_the_loop_stops_at_the_case_budget(store):
    settings = Settings(anthropic_api_key="k", max_iterations=20, model_timeout_s=50)
    provider, requests = endless_claude(settings, delay=0.2)
    gateway = build_gateway(store)
    # Wide margins: this runs in the merge gate, where a cold first call must not fail a PR.
    start = time.monotonic()
    result = run(CASE, gateway, settings, provider, deadline=start + 2.0)

    assert time.monotonic() - start < 4  # the deadline plus at most one reply in flight
    assert 2 <= len(requests) < 20
    assert result.final_state == "ERROR"
    assert result.trace[-1]["error"] == "CaseCancelled: case budget exhausted"
    assert all(r["timeout"]["read"] <= 1.0 for r in requests)  # min(50, seconds left / 2 tries)


def test_iterations_and_effort_reach_the_api(store):
    settings = Settings(anthropic_api_key="k", max_iterations=3, effort="low")
    provider, requests = endless_claude(settings, delay=0)
    run(CASE, build_gateway(store), settings, provider)
    assert len(requests) == 3
    assert requests[0]["output_config"] == {"effort": "low"}
