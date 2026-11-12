"""The QA sweep: every GET in the OpenAPI spec answers below 500. A route that only breaks at
runtime (a bad seed, a missing key, a renamed field) fails the merge gate, not the demo.

Marked live: scripts/deploy.sh runs this file again against the deployed service (BASE_URL), so
"it deployed" also means every page answers and the token is enforced there."""

import re
import tempfile
from pathlib import Path

import pytest

from starter.core.store import Store
from starter.runtime.config import Settings
from starter.runtime.factory import create_app

pytestmark = pytest.mark.live


def _get_paths() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        spec = create_app(Settings(), Store(Path(tmp) / "store.json")).openapi()
    return [path for path, ops in spec["paths"].items() if "get" in ops]


def _fill(client, auth, path: str) -> str:
    """Put a seeded id into each {param}, taken from the list route the param hangs off."""
    while m := re.search(r"{\w+}", path):
        parent = path[: m.start()].rstrip("/")
        listing = client.get(parent, headers=auth)
        is_json = listing.headers.get("content-type", "").startswith("application/json")
        rows = listing.json() if listing.status_code == 200 and is_json else None
        if not (isinstance(rows, list) and rows and isinstance(rows[0], dict) and "id" in rows[0]):
            pytest.skip(f"no seeded row with an id at GET {parent} to fill {m.group()}")
        path = path[: m.start()] + str(rows[0]["id"]) + path[m.end() :]
    return path


@pytest.mark.parametrize("path", _get_paths())
def test_every_get_route_answers_below_500(client, auth, path):
    url = _fill(client, auth, path)
    r = client.get(url, headers=auth)  # the admin token: harmless on public routes
    assert r.status_code < 500, f"GET {url} -> {r.status_code}: {r.text[:300]}"


def test_a_request_without_the_token_is_refused(client, auth):
    assert client.post("/api/runs", json={}).status_code == 401  # the route that spends money
    assert client.post("/api/mcp/token").status_code == 401
    # and the token works. Minting an MCP token on every deploy is safe: tokens are signed, not
    # stored (mcp_door.issue_token), so this POST writes nothing.
    assert client.post("/api/mcp/token", headers=auth).status_code == 200
