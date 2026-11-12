# Grok Bot and Cursor

## Grok Bot calls our MCP server

Grok Bot connects to tools as custom MCP connectors: Remote HTTPS, a server URL and optional
HTTP headers ([Use the computer and apps](https://docs.x.ai/grok-bot/computer-and-apps)). Our
`/mcp` is Streamable HTTP with a bearer token, which is exactly that. The
[grok-bot-skill](https://github.com/adamanz/grok-bot-skill) is the other direction (Cursor or
Claude Code messaging a Bot), so it is not what we need. Grok Bot runs in the cloud: it reaches
only a public URL, never localhost.

Live server: `https://xray-901257379404.europe-west1.run.app/mcp`.

Setup, on the laptop with the Grok Bot app signed in:

1. `make mcp MCP_URL=https://xray-901257379404.europe-west1.run.app/mcp` and copy the token from the printed line (it is signed with the
   deploy's `MCP_SECRET`, or `ADMIN_PASSWORD` until that secret is mounted).
2. In Grok Bot: **Connect apps > Add a custom connector**. Name `xray`, Type **Remote HTTPS**,
   Server URL `https://xray-901257379404.europe-west1.run.app/mcp`, header `Authorization: Bearer <token>`. **Add plugin**.
3. In a chat, type `@xray` to attach it, then send the demo prompts.

(Instead of step 2 you can tell a Bot: "Add a custom MCP server called xray at
https://xray-901257379404.europe-west1.run.app/mcp with header Authorization: Bearer <token>", and approve the card.)

Demo prompts, in order:

1. `@xray X-ray the listing "demo" (24 Macquarie Way, E14) and give me the Trust Score.`
2. `@xray Explain the property type finding: what does the advert say and what does the EPC register record?`
3. `@xray Why is the score 67? List each finding that cost points and its source.`

Before the demo, check the connector path without the app. This speaks Streamable HTTP with a
bearer header exactly as the connector does, runs `xray_listing` on the demo, runs
`explain_finding` on the disagreeing finding, and prints `/api/clients`:

    MCP_URL=https://xray-901257379404.europe-west1.run.app/mcp MCP_SECRET=<secret> uv run python scripts/grok_connector_check.py

It names itself `grok-connector-check`, so its calls count under `grok_bot` in `/api/clients`;
pass `--client check` to keep them out of that count.

## The same session through the xAI API

`scripts/grok_session.py` sends those two prompts to the xAI Responses API with our server as a
[remote MCP tool](https://docs.x.ai/docs/guides/tools/remote-mcp-tools)
(`{"type": "mcp", "server_url", "server_label", "authorization"}`) and saves the transcript to
`docs/media/grok-session.json`. The model is `XAI_MODEL`, default `grok-4.7`
([models](https://docs.x.ai/docs/models)).

    XAI_API_KEY=... BASE_URL=https://<deployed-url> MCP_TOKEN=<token> \
        uv run python scripts/grok_session.py

## Cursor SDK in the pipeline

`tools/cursor-step/index.ts` is one X-ray step run by a Cursor agent
([TypeScript SDK](https://cursor.com/docs/sdk/typescript)): `Agent.create` with a local runtime
and no built-in tools, `agent.send(...)`, `run.wait()`. It reads the report on stdin and writes
a plain-English summary of the findings that cites evidence ids only.
`starter/verticals/cursor_step.summarize(report)` runs it when `CURSOR_API_KEY` is set, drops any
cited id the report does not hold, and returns `None` otherwise, so the pipeline is unchanged
without a key. Once: `cd tools/cursor-step && npm install`. Model: `CURSOR_MODEL`, default
`composer-2.5`.
