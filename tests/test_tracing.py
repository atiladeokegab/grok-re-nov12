"""Tracing: OpenTelemetry spans as redacted JSON lines, one trace per HTTP request and per case."""

import json

from starter.agent.loop import run
from starter.core import tracing
from starter.core.gateway import Gateway, build_gateway
from starter.runtime.config import Settings

CASE = {"id": "t-1", "body": "A customer asks for a copy of last month's statement."}


def test_redact_hides_secret_keys_and_anthropic_keys():
    got = tracing.redact(
        {
            "api_key": "a",
            "arg.API-KEY": "b",
            "auth_token": "c",
            "password": "d",
            "client_secret": "e",
            "note": "use sk-ant-api03-Abc_12-x please",
            "nested": [{"apikey": "f"}],
            "count": 3,
        }
    )
    assert got == {
        "api_key": "[REDACTED]",
        "arg.API-KEY": "[REDACTED]",
        "auth_token": "[REDACTED]",
        "password": "[REDACTED]",
        "client_secret": "[REDACTED]",
        "note": "use [REDACTED] please",
        "nested": [{"apikey": "[REDACTED]"}],
        "count": 3,
    }


def test_gateway_call_span_is_written_redacted(store):
    gateway = Gateway(store)

    @gateway.register
    def sign_in(user: str, password: str, note: str) -> dict:
        """Sign in."""
        return {"user": user}

    with tracing.collect("test") as (trace_id, spans):
        gateway.call("sign_in", {"user": "ann", "password": "hunter2", "note": "sk-ant-x1"}, "c1")
    [call] = [s for s in spans if s["name"] == "gateway.call"]
    assert call["trace_id"] == trace_id and call["status"] == "OK"
    assert call["attributes"] == {
        "tool": "sign_in",
        "case_id": "c1",
        "simulated": True,
        "arg.user": "ann",
        "arg.password": "[REDACTED]",
        "arg.note": "[REDACTED]",
    }
    assert "hunter2" not in json.dumps(spans) and "sk-ant-" not in json.dumps(spans)


def test_a_failed_gateway_call_is_an_error_span(store):
    with tracing.collect("test") as (_, spans):
        try:
            build_gateway(store).call("send_message", {"to": "ann"}, "c1")
        except ValueError:
            pass
    [call] = [s for s in spans if s["name"] == "gateway.call"]
    assert call["status"] == "ERROR" and "Missing required argument" in call["error"]


def test_a_case_run_is_one_trace_with_model_and_gateway_spans(store):
    result = run(CASE, build_gateway(store), Settings())
    assert len(result.trace_id) == 32
    assert result.trace[0]["trace_id"] == result.trace[-1]["trace_id"] == result.trace_id
    spans = {s["name"]: s for s in result.spans}
    assert set(spans) == {"case", "model", "gateway.call"}
    assert {s["trace_id"] for s in result.spans} == {result.trace_id}
    assert spans["case"]["parent_id"] is None
    assert spans["model"]["parent_id"] == spans["case"]["span_id"]
    assert spans["gateway.call"]["parent_id"] == spans["model"]["span_id"]
    assert spans["model"]["attributes"] == {"provider": "fake", "model": "claude-opus-5-5"}
    assert run(CASE, build_gateway(store), Settings()).trace_id != result.trace_id


def test_each_http_request_is_one_trace_written_to_stdout(client, auth, capsys):
    good = {"case_id": "c1", "args": {"to": "ann", "body": "hi"}}
    assert client.post("/api/tools/send_message", json=good, headers=auth).status_code == 200
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    [log] = [x for x in lines if "request_id" in x]
    spans = [x for x in lines if x.get("trace_id") == log["trace_id"] and "span_id" in x]
    assert {s["name"] for s in spans} == {"POST /api/tools/send_message", "gateway.call"}
