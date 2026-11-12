"""Talk to a deployed /mcp the way a Grok Bot remote custom connector does: Streamable HTTP with a
bearer header, the initialize handshake, xray_listing on the demo, then explain_finding on the
disagreeing finding. It prints the answer and the server's /api/clients counts.

    MCP_URL=https://<deployed>/mcp MCP_SECRET=<the deploy's mcp secret> \
        uv run python scripts/grok_connector_check.py

MCP_TOKEN=<token from make mcp> works instead of MCP_SECRET. The client names itself
"mcp-connector-check" (counted as other); pass --client NAME to be counted elsewhere.
"""

import argparse
import asyncio
import json
import os
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from starter.runtime.mcp_door import issue_token


def _payload(result) -> dict:
    if result.is_error:
        sys.exit(f"tool error: {result.content[0].text}")
    return json.loads(result.content[0].text)["payload"]


async def check(
    url: str, token: str, name: str, listing: str, offline: bool = False, transport=None
) -> dict:
    """transport: an httpx2 transport to use instead of the network (tests pass ASGITransport)."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": f"{name}/1.0"}
    async with httpx2.AsyncClient(headers=headers, timeout=120, transport=transport) as http:
        transport = streamable_http_client(url, http_client=http)
        info = Implementation(name=name, version="1.0")
        async with Client(transport, mode="legacy", client_info=info) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert {"xray_listing", "explain_finding"} <= tools, tools
            run = {"listing_id_or_url": listing, "offline": offline}
            report = _payload(await client.call_tool("xray_listing", run))
            pick = [f for f in report["findings"] if f["verdict"] == "disagrees"]
            target = pick[0]["id"] if pick else report["run_id"]  # no disagreement: explain score
            answer = _payload(await client.call_tool("explain_finding", {"finding_id": target}))
        clients = (await http.get(url.removesuffix("/mcp") + "/api/clients")).json()
    return {"report": report, "explained": target, "answer": answer, "clients": clients}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--client", default="mcp-connector-check")
    ap.add_argument("--listing", default="demo")
    ap.add_argument("--offline", action="store_true", help="fixtures only, no network")
    args = ap.parse_args()
    url = os.environ.get("MCP_URL") or sys.exit("set MCP_URL=https://<deployed>/mcp")
    token = os.environ.get("MCP_TOKEN") or (
        issue_token(os.environ["MCP_SECRET"]) if os.environ.get("MCP_SECRET") else None
    )
    if not token:
        sys.exit("set MCP_SECRET (the deploy's mcp secret) or MCP_TOKEN")
    out = asyncio.run(check(url, token, args.client, args.listing, args.offline))
    r = out["report"]
    print(f"trust_score={r['trust_score']} counts={r['counts']} run_id={r['run_id']}")
    print(f"sources={[(s['name'], s['status'], s['ms']) for s in r['sources']]}")
    print(f"explain_finding({out['explained']}):")
    print(json.dumps(out["answer"], indent=1)[:3000])
    print(f"/api/clients={out['clients']}")


if __name__ == "__main__":
    main()
