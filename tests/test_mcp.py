"""The MCP door, driven by the official MCP client over Streamable HTTP, in process."""

import asyncio
import json

import httpx2
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from starter.runtime.config import Settings
from starter.runtime.factory import create_app


def mcp(app, token: str, action, modes=("auto",)) -> list:
    """Run action(client) once per protocol mode ("auto" = 2026 protocol, "legacy" = the
    initialize handshake older clients use) inside one app lifespan; return the results."""

    async def go():
        results = []
        async with app.router.lifespan_context(app):
            for mode in modes:
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app),
                    headers={"Authorization": f"Bearer {token}"},
                ) as http:
                    transport = streamable_http_client("http://testserver/mcp", http_client=http)
                    async with Client(transport, mode=mode) as client:
                        results.append(await action(client))
        return results

    return asyncio.run(go())


def token_for(client, auth) -> str:
    r = client.post("/api/mcp/token", headers=auth)
    assert r.status_code == 200
    return r.json()["token"]


def test_token_needs_admin_login(client):
    assert client.post("/api/mcp/token").status_code == 401


def test_lists_the_gateway_tools_in_both_protocol_modes(client, auth):
    results = mcp(client.app, token_for(client, auth), Client.list_tools, ("auto", "legacy"))
    for result in results:
        assert {t.name for t in result.tools} == set(client.app.state.gateway.tools)
        send = next(t for t in result.tools if t.name == "send_message")
        assert send.input_schema["required"] == ["to", "body"]


def test_a_call_is_audited_through_the_gateway(client, auth, store):
    token = token_for(client, auth)
    args = {"to": "ann", "body": "hi"}
    [result] = mcp(client.app, token, lambda c: c.call_tool("send_message", args))
    assert not result.is_error and '"SIMULATED"' in result.content[0].text
    [event] = [e for e in store.snapshot()["events"] if e["type"] == "tool_call"]
    assert (event["tool"], event["args"]) == ("send_message", args)
    assert event["case_id"] == f"mcp-{token.split('.')[0]}"


def test_missing_or_bad_token_is_401(client, auth):
    sid = token_for(client, auth).split(".")[0]
    for headers in ({}, {"Authorization": f"Bearer {sid}.forged"}, {"Authorization": "Bearer x"}):
        assert client.post("/mcp", json={}, headers=headers).status_code == 401


def test_xray_listing_over_mcp_matches_run_xray_and_is_counted(client, auth, tmp_path):
    from starter.core.gateway import build_gateway
    from starter.core.store import Store
    from starter.verticals.xray import run_xray

    def go(c):
        return c.call_tool("xray_listing", {"listing_id_or_url": "demo", "offline": True})

    [result] = mcp(client.app, token_for(client, auth), go)
    report = json.loads(result.content[0].text)["payload"]
    direct = run_xray(build_gateway(Store(tmp_path / "s.json")), "demo", offline=True)
    assert report["trust_score"] == direct.trust_score
    pick = ("field", "verdict", "severity", "evidence_ids")
    assert [[f[k] for k in pick] for f in report["findings"]] == [
        [getattr(f, k) for k in pick] for f in direct.findings
    ]
    stored = client.get(f"/api/xray/{report['run_id']}").json()
    assert stored["client_calls"]["mcp"] == {"grok_bot": 0, "cursor": 0, "other": 1}
    assert client.get("/api/clients").json() == {"mcp": {"grok_bot": 0, "cursor": 0, "other": 1}}


def test_client_is_named_by_user_agent_or_client_info():
    from starter.runtime.mcp_door import TokenGuard, client_kind

    assert [client_kind(n) for n in ("Grok Bot", "xAI-agent", "Cursor/1.2", "claude-code")] == [
        "grok_bot",
        "grok_bot",
        "cursor",
        "other",
    ]
    init = json.dumps({"method": "initialize", "params": {"clientInfo": {"name": "cursor-vscode"}}})
    assert TokenGuard._client("s1", init.encode(), b"") == "cursor"
    assert TokenGuard._client("s1", b'{"method": "tools/call"}', b"") == "cursor"  # remembered
    meta = {"_meta": {"io.modelcontextprotocol/clientInfo": {"name": "grok"}}}
    assert TokenGuard._client("s2", json.dumps({"params": meta}).encode(), b"") == "grok_bot"
    assert TokenGuard._client("s3", b"", b"xai-grok-bot/1.0") == "grok_bot"


def test_mcp_tokens_are_signed_with_mcp_secret_not_the_admin_password(store):
    from starter.runtime import mcp_door

    app = create_app(Settings(mcp_secret="mcp-only"), store)
    good, admin = mcp_door.issue_token("mcp-only"), mcp_door.issue_token("admin")
    [tools] = mcp(app, good, Client.list_tools)
    assert "xray_listing" in {t.name for t in tools.tools}
    http = TestClient(app)  # no lifespan: mcp() above already ran the session manager
    forged = http.post("/mcp", json={}, headers={"Authorization": f"Bearer {admin}"})
    assert forged.status_code == 401
    login = http.post("/api/login", json={"password": "admin"}).json()["token"]
    minted = http.post("/api/mcp/token", headers={"Authorization": f"Bearer {login}"})
    assert mcp_door.session_of(minted.json()["token"], "mcp-only")


def test_mcp_secret_falls_back_to_admin_password_until_deploy_carries_it():
    env = {"MODE": "cloud", "ANTHROPIC_API_KEY": "k", "ADMIN_PASSWORD": "pw"}
    assert Settings.from_env({**env, "DATA_PATH": "gs://b/s"}).mcp_key == "pw"
    assert Settings.from_env({**env, "DATA_PATH": "gs://b/s", "MCP_SECRET": "m"}).mcp_key == "m"
    assert Settings.from_env({}).mcp_key == "admin"  # local falls back to the admin password


def test_trace_finding_unknown_id_is_an_mcp_tool_error_not_a_500(client, auth):
    [result] = mcp(
        client.app,
        token_for(client, auth),
        lambda c: c.call_tool("trace_finding", {"finding_id": "f-nope"}),
    )
    assert result.is_error and "no finding 'f-nope'" in result.content[0].text
