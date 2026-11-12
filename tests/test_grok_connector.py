"""The Grok Bot connector path, in process: scripts/grok_connector_check.check() speaks Streamable
HTTP with a bearer token to create_app's /mcp, X-rays the offline demo and explains the
disagreement, exactly as the CLI does against a deploy."""

import asyncio
import importlib.util
from pathlib import Path

import httpx2

from starter.runtime import mcp_door
from starter.runtime.config import Settings
from starter.runtime.factory import create_app
from starter.verticals import narrate

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "grok_check", ROOT / "scripts/grok_connector_check.py"
)
grok_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grok_check)


def test_grok_connector_flow_on_the_offline_demo(store):
    app = create_app(Settings(mcp_secret="mcp-only"), store)
    token = mcp_door.issue_token("mcp-only")

    async def run():
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            url = "http://testserver/mcp"
            grok = await grok_check.check(
                url, token, "grok-connector-check", "demo", True, transport
            )
            other = await grok_check.check(url, token, "check", "demo", True, transport)
        return grok, other

    grok, other = asyncio.run(run())
    report = grok["report"]
    assert report["trust_score"] == 67
    [f] = [f for f in report["findings"] if f["id"] == grok["explained"]]
    assert (f["field"], f["verdict"]) == ("property_type", "disagrees")
    assert "End-terrace house" in str(grok["answer"])
    assert grok["clients"]["mcp"]["grok_bot"] >= 2
    assert other["clients"]["mcp"]["other"] >= grok["clients"]["mcp"].get("other", 0) + 2
    assert other["clients"]["mcp"]["grok_bot"] == grok["clients"]["mcp"]["grok_bot"]


def test_one_xai_model_default(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.delenv("XAI_MODEL", raising=False)
    assert narrate.provider() == ("xai", narrate.XAI_MODEL) == ("xai", "grok-4.7")
