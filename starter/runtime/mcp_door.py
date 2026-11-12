"""The MCP door: the gateway's tools over Streamable HTTP at /mcp, for any MCP client (Claude Code,
another agent). Every call goes through Gateway.call, so it is validated and audited like any
other. A caller needs a bearer token from POST /api/mcp/token (admin login); `make mcp` mints one
and prints the `claude mcp add` line.

    uv run python -m starter.runtime.mcp_door [URL]
"""

import functools
import hashlib
import hmac
import json
import secrets
import sys
from contextvars import ContextVar

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from starter.core.gateway import Gateway
from starter.runtime.config import Settings

SESSION: ContextVar[str] = ContextVar("mcp_session", default="unknown")
CLIENT: ContextVar[str | None] = ContextVar("mcp_client", default=None)  # None: not over MCP
CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"  # the 2026 protocol sends it per request
# shortcut: per instance, lost on restart; legacy clients send clientInfo only on initialize, so a
# later call on another instance falls back to its User-Agent.
_clients: dict[str, str] = {}  # session id -> client


def client_kind(name: str) -> str:
    name = name.lower()
    return (
        "grok_bot" if "grok" in name or "xai" in name else "cursor" if "cursor" in name else "other"
    )


def issue_token(password: str) -> str:
    """A new session token, '<session id>.<signature>'. Valid on every instance, no storage."""
    # ponytail: tokens never expire and can't be revoked one by one; rotating ADMIN_PASSWORD
    # revokes them all. Store issued ids with an expiry if MCP access ever outlives the event.
    sid = secrets.token_hex(8)  # password: Settings.mcp_key, never ADMIN_PASSWORD in cloud
    return f"{sid}.{_sign(password, sid)}"


def session_of(token: str, password: str) -> str | None:
    """The session id if the token is ours, else None."""
    sid, _, sig = token.partition(".")
    return sid if sid and hmac.compare_digest(sig, _sign(password, sid)) else None


def _sign(password: str, sid: str) -> str:
    return hmac.new(password.encode(), f"mcp:{sid}".encode(), hashlib.sha256).hexdigest()


def build_mcp(gateway: Gateway) -> MCPServer:
    """An MCP server offering every gateway tool; the audit case id is 'mcp-<session id>'."""
    server = MCPServer("starter")

    def bind(name: str, fn):
        @functools.wraps(fn)  # the tool's signature and docstring become its MCP schema
        def call(**args):
            result = gateway.call(name, args, f"mcp-{SESSION.get()}")
            gateway.store.mutate(functools.partial(_tally, CLIENT.get() or "other"))
            return result

        return call

    for name, fn in gateway.tools.items():
        server.add_tool(bind(name, fn), name=name, structured_output=False)
    return server


def _tally(client: str, data: dict) -> None:
    """One more MCP tool call by this client: GET /api/clients."""
    tally = data.setdefault("mcp_clients", {})
    tally[client] = tally.get(client, 0) + 1


def asgi_app(server: MCPServer):
    """The Streamable HTTP app. Stateless, so any Cloud Run instance can answer any request;
    no DNS-rebinding host check, because the bearer token is the gate and the host varies."""
    return server.streamable_http_app(
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


class TokenGuard:
    """ASGI wrapper: 401 unless the request carries a token from issue_token."""

    def __init__(self, app, password: str):
        self.app, self.password = app, password

    async def __call__(self, scope, receive, send):
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        sid = session_of(auth.removeprefix("Bearer "), self.password)
        if sid is None:
            response = JSONResponse({"error": "MCP token required: POST /api/mcp/token"}, 401)
            return await response(scope, receive, send)
        body, more = b"", True
        while more:  # read the request to find clientInfo, then hand the same bytes on
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        SESSION.set(sid)
        CLIENT.set(self._client(sid, body, dict(scope["headers"]).get(b"user-agent", b"")))
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    def _client(sid: str, body: bytes, user_agent: bytes) -> str:
        try:
            params = json.loads(body).get("params") or {}
            info = params.get("clientInfo") or (params.get("_meta") or {}).get(CLIENT_INFO_KEY)
        except (ValueError, AttributeError):
            info = None
        if isinstance(info, dict) and info.get("name"):
            _clients[sid] = client_kind(info["name"])
        return _clients.get(sid) or client_kind(user_agent.decode(errors="replace"))


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"
    token = issue_token(Settings.from_env().mcp_key)
    print(f'claude mcp add --transport http starter {url} --header "Authorization: Bearer {token}"')
