from starter.agent.cases import load_case, strip_outcome
from starter.agent.loop import AgentResult, FakeProvider, parse_state, run
from starter.core.gateway import build_gateway
from starter.runtime.config import Settings

CASE = {"id": "sample-1", "body": "A customer asks for a copy of last month's statement."}


def test_offline_run_takes_a_simulated_action_and_answers(store):
    result = run(CASE, build_gateway(store), Settings())
    assert isinstance(result, AgentResult)
    assert result.final_answer and result.final_state == "DONE"
    assert [a["status"] for a in result.actions] == ["SIMULATED"]
    assert result.actions[0]["tool"] == "send_message"
    first = result.trace[0]
    assert first["type"] == "model_input" and first["provider"] == "fake"
    assert "sample-1" in first["messages"][0]["content"]
    assert {"send_message", "list_items", "get_skill"} <= {t["name"] for t in first["tools"]}


def test_every_trace_step_has_tool_status_and_error(store):
    trace = run(CASE, build_gateway(store), Settings()).trace
    assert [s["type"] for s in trace] == ["model_input", "tool_call", "final"]
    for s in trace:
        assert {"tool", "status", "error"} <= s.keys()
        assert s["status"] in {"SIMULATED", "OK", "ERROR"}
    assert (trace[1]["tool"], trace[1]["status"], trace[1]["error"]) == (
        "send_message",
        "SIMULATED",
        None,
    )
    assert trace[-1]["final_state"] == "DONE"


def test_failing_tool_call_writes_error_status_and_text(store):
    class BadArgs:
        name = "test"

        def run(self, system, messages, tools, trace, seconds_left):
            send = next(t for t in tools if t.name == "send_message")
            try:
                send.call({"to": "ann"})
            except ValueError:
                pass
            return "Could not send.\nSTATE: NEEDS_INFO", ""

    result = run(CASE, build_gateway(store), Settings(), BadArgs())
    failed = result.trace[1]
    assert (failed["type"], failed["tool"], failed["status"]) == (
        "tool_call",
        "send_message",
        "ERROR",
    )
    assert "body" in failed["error"] and "Missing required argument" in failed["error"]
    assert result.final_state == "NEEDS_INFO"


def test_final_state_comes_from_the_state_line_and_defaults_to_error():
    assert parse_state("Booked.\nSTATE: ESCALATED") == ("ESCALATED", "Booked.")
    assert parse_state("STATE: DONE\nmore\nSTATE: NEEDS_INFO") == ("NEEDS_INFO", "more")
    assert parse_state("No marker.") == ("ERROR", "No marker.")
    assert parse_state("STATE: MAYBE") == ("ERROR", "STATE: MAYBE")


def test_a_crashing_provider_still_returns_an_error_result(store):
    class Broken:
        name = "test"

        def run(self, system, messages, tools, trace, seconds_left):
            raise RuntimeError("API down")

    result = run(CASE, build_gateway(store), Settings(), Broken())
    assert result.final_state == "ERROR"
    assert result.trace[-1]["error"] == "RuntimeError: API down"


def test_no_key_means_fake_provider(store):
    assert run(CASE, build_gateway(store), Settings()).trace[0]["provider"] == FakeProvider.name


def test_strip_outcome_cuts_only_the_outcome_section(tmp_path):
    text = "# Case\n\nBody.\n\n## Outcome\n\nSECRET\n\n## History\n\nEarlier."
    assert strip_outcome(text) == "# Case\n\nBody.\n\n## History\n\nEarlier."
    (tmp_path / "index.md").write_text(text)
    assert load_case(tmp_path)["body"] == strip_outcome(text)


def test_run_endpoint_stores_run_and_page_lists_it(client, auth):
    body = {"id": "web-1", "body": "Hello\n\n## Outcome\n\nSECRET"}
    r = client.post("/api/runs", json=body, headers=auth)
    assert r.status_code == 200
    assert "SECRET" not in str(r.json()["trace"][0])
    page = client.get("/runs")
    assert page.status_code == 200 and "Case web-1" in page.text and "SIMULATED" in page.text
    assert client.get("/static/tokens.css").status_code == 200
