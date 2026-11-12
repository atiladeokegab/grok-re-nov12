import pytest

from starter.core.errors import NotFound
from starter.core.gateway import Gateway, build_gateway


def test_effect_tool_is_simulated_and_audited_for_any_case(store):
    gateway = build_gateway(store)
    result = gateway.call("send_message", {"to": "ann", "body": "hi"}, case_id="any-case-42")
    assert result == {"status": "SIMULATED", "payload": {"to": "ann", "body": "hi"}}
    [event] = store.snapshot()["events"]
    assert (event["type"], event["case_id"], event["tool"]) == (
        "tool_call",
        "any-case-42",
        "send_message",
    )


def test_read_tool_is_ok_not_simulated(store):
    gateway = build_gateway(store)
    assert gateway.call("get_skill", {"name": "escalation"}, case_id="c1")["status"] == "OK"


def test_bad_args_raise_value_error_and_are_not_audited(store):
    gateway = build_gateway(store)
    with pytest.raises(ValueError):
        gateway.call("send_message", {"to": "ann"}, case_id="c1")
    with pytest.raises(ValueError):
        gateway.call("send_message", {"to": "ann", "body": "hi", "cc": "bob"}, case_id="c1")
    with pytest.raises(NotFound):
        gateway.call("launch_rocket", {}, case_id="c1")
    assert store.snapshot()["events"] == []


def test_register_reads_type_hints(store):
    gateway = Gateway(store)

    @gateway.register
    def refund(amount: int) -> dict:
        """Refund an amount."""
        return {"amount": amount}

    assert gateway.call("refund", {"amount": "5"}, "c1")["payload"] == {"amount": 5}
    with pytest.raises(ValueError):
        gateway.call("refund", {"amount": "five"}, "c1")


def test_api_maps_bad_args_to_422_and_needs_login(client, auth):
    good = {"case_id": "c1", "args": {"to": "ann", "body": "hi"}}
    assert client.post("/api/tools/send_message", json=good).status_code == 401
    r = client.post("/api/tools/send_message", json=good, headers=auth)
    assert (r.status_code, r.json()["status"]) == (200, "SIMULATED")
    bad = {"case_id": "c1", "args": {"to": "ann"}}
    assert client.post("/api/tools/send_message", json=bad, headers=auth).status_code == 422
    assert client.post("/api/tools/nope", json=good, headers=auth).status_code == 404


def live_and_simulated(store):
    """Two gateways over one store, each with an effect tool whose body is a real side effect."""
    ran = []

    def wire(gateway):
        @gateway.register
        def charge_card(card: str, amount: int) -> dict:
            """Charge a card."""
            ran.append((card, amount))
            raise RuntimeError("a real charge would happen here")

        @gateway.register(simulate=lambda to, body: {"would_send_to": to})
        def send_sms(to: str, body: str) -> dict:
            """Send an SMS."""
            ran.append((to, body))
            return {"sent": True}

        return gateway

    return wire(Gateway(store)), wire(Gateway(store, effects="live")), ran


def test_simulate_mode_never_runs_an_effect_tool(store):
    simulated, _, ran = live_and_simulated(store)
    result = simulated.call("charge_card", {"card": "4242", "amount": "5"}, "c1")
    assert result == {"status": "SIMULATED", "payload": {"card": "4242", "amount": 5}}
    sms = simulated.call("send_sms", {"to": "ann", "body": "hi"}, "c1")
    assert sms == {"status": "SIMULATED", "payload": {"would_send_to": "ann"}}
    assert ran == []
    with pytest.raises(ValueError):  # arguments are still checked without running anything
        simulated.call("charge_card", {"card": "4242", "amount": "five"}, "c1")


def test_live_mode_runs_effect_tools(store):
    _, live, ran = live_and_simulated(store)
    assert live.call("send_sms", {"to": "ann", "body": "hi"}, "c1") == {
        "status": "OK",
        "payload": {"sent": True},
    }
    with pytest.raises(RuntimeError, match="a real charge"):
        live.call("charge_card", {"card": "4242", "amount": 5}, "c1")
    assert ran == [("ann", "hi"), ("4242", 5)]


def test_a_duplicate_tool_name_is_refused(store):
    gateway = build_gateway(store)
    with pytest.raises(ValueError, match="'send_message' is already registered"):

        @gateway.register
        def send_message(to: str) -> dict:
            """A second tool with a taken name."""
            return {}


def test_latency_waits_before_a_simulated_effect_only(store, monkeypatch):
    waits = []
    monkeypatch.setattr("starter.core.gateway.time.sleep", waits.append)
    gateway = build_gateway(store, latency=(0.35, 1.0))
    gateway.call("send_message", {"to": "ann", "body": "hi"}, case_id="c1")
    gateway.call("get_skill", {"name": "escalation"}, case_id="c1")
    assert len(waits) == 1 and 0.35 <= waits[0] <= 1.0
