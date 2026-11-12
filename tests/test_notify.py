"""send_email (Resend) and place_call (ElevenLabs): simulated with no network by default; live, a
fake transport proves the request each provider is sent."""

import json

import httpx2
import pytest

from starter.core.errors import ProviderNotConfigured
from starter.core.gateway import build_gateway
from starter.verticals import notify

EMAIL = {"to": "ada@example.com", "subject": "Your case", "body": "It is resolved."}
CALL = {"to_number": "+447700900123", "reason": "Confirm the viewing time"}
KEYS = {
    "RESEND_API_KEY": "re_test",
    "EMAIL_FROM": "Team <team@example.com>",
    "ELEVENLABS_API_KEY": "xi_test",
    "ELEVENLABS_AGENT_ID": "agent_1",
    "ELEVENLABS_PHONE_NUMBER_ID": "phnum_1",
}


@pytest.fixture
def sent(monkeypatch):
    """Every request the adapters make, answered the way each provider answers."""
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.host == "api.resend.com":
            return httpx2.Response(200, json={"id": "email_1"})
        return httpx2.Response(200, json={"success": True, "message": "ok", "callSid": "CA1"})

    monkeypatch.setattr(notify, "transport", httpx2.MockTransport(handler))
    return requests


@pytest.fixture
def keys(monkeypatch):
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)


def test_simulated_by_default_even_with_keys(store, sent, keys):
    gateway = build_gateway(store)
    assert gateway.call("send_email", EMAIL, "c1") == {"status": "SIMULATED", "payload": EMAIL}
    assert gateway.call("place_call", CALL, "c1")["status"] == "SIMULATED"
    assert sent == []


def test_live_email_is_one_resend_request(store, sent, keys):
    gateway = build_gateway(store, "live")
    result = gateway.call("send_email", EMAIL, "c1")
    assert result == {"status": "OK", "payload": {"id": "email_1"}}
    [request] = sent
    assert (request.method, str(request.url)) == ("POST", "https://api.resend.com/emails")
    assert request.headers["authorization"] == "Bearer re_test"
    assert request.headers["idempotency-key"]
    assert json.loads(request.content) == {
        "from": "Team <team@example.com>",
        "to": ["ada@example.com"],
        "subject": "Your case",
        "text": "It is resolved.",
    }


def test_live_call_is_one_elevenlabs_request(store, sent, keys):
    gateway = build_gateway(store, "live")
    assert gateway.call("place_call", CALL, "c1")["payload"]["callSid"] == "CA1"
    [request] = sent
    assert str(request.url) == "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
    assert request.headers["xi-api-key"] == "xi_test"
    assert json.loads(request.content) == {
        "agent_id": "agent_1",
        "agent_phone_number_id": "phnum_1",
        "to_number": "+447700900123",
        "conversation_initiation_client_data": {
            "dynamic_variables": {"reason": "Confirm the viewing time"}
        },
    }


def test_a_repeat_in_the_case_sends_once(store, sent, keys):
    gateway = build_gateway(store, "live")
    first = gateway.call("send_email", EMAIL, "c1")
    assert gateway.call("send_email", EMAIL, "c1") == first
    assert len(sent) == 1


@pytest.mark.parametrize("missing", ["RESEND_API_KEY", "EMAIL_FROM"])
def test_live_email_without_its_settings_sends_nothing(store, sent, keys, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(ProviderNotConfigured, match=missing):
        build_gateway(store, "live").call("send_email", EMAIL, "c1")
    assert sent == []


def test_live_call_without_its_settings_fails_and_sends_nothing(store, sent, keys, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_AGENT_ID")
    with pytest.raises(ProviderNotConfigured, match="ELEVENLABS_AGENT_ID"):
        build_gateway(store, "live").call("place_call", CALL, "c1")
    assert sent == []


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("send_email", {**EMAIL, "to": "not an address"}),
        ("place_call", {**CALL, "to_number": "07700 900123"}),
    ],
)
def test_bad_recipients_are_rejected_before_anything_runs(store, sent, tool, args):
    with pytest.raises(ValueError):
        build_gateway(store).call(tool, args, "c1")
    assert sent == []
