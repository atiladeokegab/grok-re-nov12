"""The MCP door, driven by the official MCP client over Streamable HTTP, in process."""

import asyncio

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


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
