"""Grok X-rays the demo listing through our MCP server, called by xAI as a remote MCP tool, and
saves the transcript to docs/media/grok-session.json. Costs money; run it by hand, never in CI.

    XAI_API_KEY=... BASE_URL=https://<deployed> MCP_TOKEN=<from make mcp> \\
        uv run python scripts/grok_session.py

xAI's servers call BASE_URL/mcp, so BASE_URL must be public: localhost will not work.
Request shape: https://docs.x.ai/docs/guides/tools/remote-mcp-tools
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

PROMPTS = ["X-ray 24 Macquarie Way, E14", "Why is the score 67?"]
OUT = Path(__file__).resolve().parent.parent / "docs" / "media" / "grok-session.json"


def ask(key: str, model: str, tool: dict, messages: list[dict]) -> dict:
    req = urllib.request.Request(
        "https://api.x.ai/v1/responses",
        data=json.dumps({"model": model, "input": messages, "tools": [tool]}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def text_of(response: dict) -> str:
    return "".join(
        c.get("text", "")
        for item in response.get("output", [])
        if item.get("type") == "message"
        for c in item.get("content", [])
    )


def main() -> int:
    env = {k: os.environ.get(k, "") for k in ("XAI_API_KEY", "BASE_URL", "MCP_TOKEN")}
    if missing := [k for k, v in env.items() if not v]:
        print(f"set {', '.join(missing)}", file=sys.stderr)
        return 2
    if "localhost" in env["BASE_URL"] or "127.0.0.1" in env["BASE_URL"]:
        print("BASE_URL must be the deployed URL: xAI cannot reach localhost", file=sys.stderr)
        return 2
    model = os.environ.get("XAI_MODEL") or "grok-4.7"
    tool = {
        "type": "mcp",
        "server_url": env["BASE_URL"].rstrip("/") + "/mcp",
        "server_label": "xray",
        "server_description": "Property listing X-ray: checks an advert against public records.",
        "authorization": env["MCP_TOKEN"],  # xAI sends it as the Authorization header
    }
    messages, turns = [], []
    for prompt in PROMPTS:
        messages.append({"role": "user", "content": prompt})
        response = ask(env["XAI_API_KEY"], model, tool, messages)
        answer = text_of(response)
        messages.append({"role": "assistant", "content": answer})
        calls = [i for i in response.get("output", []) if i.get("type", "").startswith("mcp")]
        turns.append(
            {"prompt": prompt, "answer": answer, "mcp_calls": calls, "id": response.get("id")}
        )
        print(f"> {prompt}\n{answer}\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # the token is not saved: only the server URL and what Grok did with it
    session = {"model": model, "server_url": tool["server_url"], "turns": turns}
    OUT.write_text(json.dumps(session, indent=2) + "\n")
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
