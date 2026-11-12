"""Notifications: send_email through Resend and place_call through an ElevenLabs agent. Both are
effect tools, so the gateway simulates them (SIMULATED, no network) unless EFFECTS=live. Live
without the provider's settings raises ProviderNotConfigured (HTTP 503): never a faked send."""

import hashlib
import json
from typing import Annotated

import httpx2
from pydantic import Field

from starter.core.errors import ProviderNotConfigured
from starter.core.gateway import current_case
from starter.runtime.config import Settings

RESEND_URL = "https://api.resend.com/emails"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"
TIMEOUT_S = 20
transport: httpx2.BaseTransport | None = None  # tests put an httpx2.MockTransport here

Email = Annotated[str, Field(pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")]
Phone = Annotated[str, Field(pattern=r"^\+[1-9]\d{6,14}$")]  # E.164


def _settings(*names: str) -> Settings:
    settings = Settings.from_env()
    missing = [n for n in names if not getattr(settings, n.lower())]
    if missing:
        raise ProviderNotConfigured(f"live effects need {', '.join(missing)}")
    return settings


def _post(url: str, headers: dict, body: dict) -> dict:
    with httpx2.Client(transport=transport, timeout=TIMEOUT_S) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def register_tools(gateway) -> None:
    @gateway.register(idempotent=True)
    def send_email(to: Email, subject: str, body: str) -> dict:
        """Email a person about their case.

        Args:
            to: The recipient's email address.
            subject: The subject line.
            body: The message, plain text.
        """
        s = _settings("RESEND_API_KEY", "EMAIL_FROM")
        case = (current_case.get() or {}).get("id", "")
        # Resend drops a repeat key for 24 h: a retry from another instance cannot send twice.
        key = hashlib.sha256(json.dumps([case, to, subject, body]).encode()).hexdigest()
        headers = {"Authorization": f"Bearer {s.resend_api_key}", "Idempotency-Key": key}
        payload = {"from": s.email_from, "to": [to], "subject": subject, "text": body}
        return _post(RESEND_URL, headers, payload)

    @gateway.register(idempotent=True)
    def place_call(to_number: Phone, reason: str) -> dict:
        """Phone a person: the voice agent calls them and handles the conversation.

        Args:
            to_number: The number to call, in E.164 form, e.g. +447700900123.
            reason: Why the agent is calling, passed to it as the {{reason}} variable.
        """
        s = _settings("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID")
        payload = {
            "agent_id": s.elevenlabs_agent_id,
            "agent_phone_number_id": s.elevenlabs_phone_number_id,
            "to_number": to_number,
            "conversation_initiation_client_data": {"dynamic_variables": {"reason": reason}},
        }
        return _post(ELEVENLABS_URL, {"xi-api-key": s.elevenlabs_api_key}, payload)
