import os

import httpx2
import pytest
from fastapi.testclient import TestClient

from starter.core.store import Store
from starter.core.tracing import EXPORTER
from starter.runtime.config import Settings
from starter.runtime.deps import session_token
from starter.runtime.factory import create_app
from starter.verticals import xray_limit

LIVE_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # read before offline_env clears it


def live_url(request) -> str | None:
    """BASE_URL, for a test marked live: only those run against a deployed service, so a stray
    BASE_URL never sends the other tests' writes to production."""
    return os.environ.get("BASE_URL") if request.node.get_closest_marker("live") else None


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    """Tests never see the developer's keys: every test runs offline, in local mode."""
    for name in (
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "CURSOR_API_KEY",
        "MCP_SECRET",
        "ADMIN_PASSWORD",
        "MODE",
        "DATA_PATH",
        "MODEL",
        "DEMO_LATENCY",
        "COMPANIES_HOUSE_API_KEY",
        "XRAY_PER_IP_PER_MIN",
        "XRAY_GLOBAL_PER_MIN",
    ):
        monkeypatch.delenv(name, raising=False)
    xray_limit.reset()  # POST /api/xray budgets start empty in every test
    monkeypatch.setattr(EXPORTER, "echo", False)  # create_app turns it on; off between tests


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store.json")


@pytest.fixture
def client(store, request):
    """The app in-process; a live test with BASE_URL set talks to that service instead."""
    if url := live_url(request):
        with httpx2.Client(base_url=url, timeout=30) as live:
            yield live
    else:
        yield TestClient(create_app(Settings(), store))


@pytest.fixture
def auth(request):
    password = LIVE_ADMIN_PASSWORD if live_url(request) else Settings().admin_password
    if password is None:
        pytest.fail("a live run needs ADMIN_PASSWORD, the deployed service's admin password")
    return {"Authorization": f"Bearer {session_token(password)}"}
