"""The MCP door: the gateway's tools over Streamable HTTP at /mcp, for any MCP client (Claude Code,
another agent). Every call goes through Gateway.call, so it is validated and audited like any
other. A caller needs a bearer token from POST /api/mcp/token (admin login); `make mcp` mints one
and prints the `claude mcp add` line.

    uv run python -m starter.runtime.mcp_door [URL]
"""

import functools
import hashlib
import hmac
import secrets
import sys
from contextvars import ContextVar

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from starter.core.gateway import Gateway
from starter.runtime.config import Settings

SESSION: ContextVar[str] = ContextVar("mcp_session", default="unknown")


def issue_token(password: str) -> str:
    """A new session token, '<session id>.<signature>'. Valid on every instance, no storage."""
    # ponytail: tokens never expire and can't be revoked one by one; rotating ADMIN_PASSWORD
    # revokes them all. Store issued ids with an expiry if MCP access ever outlives the event.
    sid = secrets.token_hex(8)
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
            return gateway.call(name, args, f"mcp-{SESSION.get()}")

        return call

    for name, fn in gateway.tools.items():
        server.add_tool(bind(name, fn), name=name, structured_output=False)
    return server


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
        SESSION.set(sid)
        await self.app(scope, receive, send)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"
    token = issue_token(Settings.from_env().admin_password)
    print(f'claude mcp add --transport http starter {url} --header "Authorization: Bearer {token}"')
