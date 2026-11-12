"""An idempotent effect tool runs once per case and arguments: a repeat gets the first result back
and is audited as a repeat, and an effect that happened is never reported as failed."""

import threading

import pytest

from starter.core.gateway import Gateway


def emailer(store, effects="simulate"):
    """A gateway with one idempotent email tool; `sent` records every real or simulated send."""
    gateway, sent = Gateway(store, effects), []

    def simulate(to: str, count: int) -> dict:
        sent.append(("simulated", to, count))
        return {"would_send_to": to}

    @gateway.register(idempotent=True, simulate=simulate)
    def send_email(to: str, count: int) -> dict:
        """Send an email."""
        sent.append(("live", to, count))
        return {"sent_to": to}

    return gateway, sent


def audit(store) -> list[dict]:
    return [e for e in store.snapshot()["events"] if e["type"] == "tool_call"]


def test_a_repeat_returns_the_first_result_and_sends_nothing(store):
    gateway, sent = emailer(store)
    first = gateway.call("send_email", {"to": "ann", "count": 1}, "c1")
    again = gateway.call("send_email", {"to": "ann", "count": "1"}, "c1")  # same once checked
    assert again == first == {"status": "SIMULATED", "payload": {"would_send_to": "ann"}}
    assert sent == [("simulated", "ann", 1)]
    assert [e.get("repeat", False) for e in audit(store)] == [False, True]


def test_live_repeat_runs_the_tool_once(store):
    gateway, sent = emailer(store, effects="live")
    for _ in range(3):
        assert gateway.call("send_email", {"to": "ann", "count": 1}, "c1")["status"] == "OK"
    assert sent == [("live", "ann", 1)]


def test_other_arguments_or_cases_are_not_repeats(store):
    gateway, sent = emailer(store)
    gateway.call("send_email", {"to": "ann", "count": 1}, "c1")
    gateway.call("send_email", {"to": "bob", "count": 1}, "c1")
    gateway.call("send_email", {"to": "ann", "count": 1}, "c2")
    assert len(sent) == 3


def test_a_tool_not_marked_idempotent_still_runs_every_time(store):
    gateway, ran = Gateway(store, effects="live"), []

    @gateway.register
    def send_sms(to: str) -> dict:
        """Send an SMS."""
        ran.append(to)
        return {}

    gateway.call("send_sms", {"to": "ann"}, "c1")
    gateway.call("send_sms", {"to": "ann"}, "c1")
    assert ran == ["ann", "ann"]


def test_a_failed_first_call_is_not_remembered(store):
    gateway, tries = Gateway(store, effects="live"), []

    @gateway.register(idempotent=True)
    def charge(card: str) -> dict:
        """Charge a card."""
        tries.append(card)
        if len(tries) == 1:
            raise RuntimeError("provider down, nothing charged")
        return {"charged": card}

    with pytest.raises(RuntimeError):
        gateway.call("charge", {"card": "4242"}, "c1")
    assert gateway.call("charge", {"card": "4242"}, "c1")["payload"] == {"charged": "4242"}
    assert len(tries) == 2 and len(audit(store)) == 1


def test_a_live_effect_cancelled_mid_call_is_still_reported_and_audited(store):
    gateway, cancel = Gateway(store, effects="live"), threading.Event()

    @gateway.register(idempotent=True)
    def send_email(to: str) -> dict:
        """Send an email; the runner gives up on the case while it is in flight."""
        cancel.set()
        return {"sent_to": to}

    result = gateway.call("send_email", {"to": "ann"}, "c1", cancel)
    assert result == {"status": "OK", "payload": {"sent_to": "ann"}}
    [event] = audit(store)
    assert event["result"] == result
