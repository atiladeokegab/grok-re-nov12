import json

from fastapi.testclient import TestClient

from starter.core.errors import ConflictError, NotFound, ProviderNotConfigured
from starter.runtime.config import Settings
from starter.runtime.factory import create_app


def test_healthz_reports_public_status(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "mode": "local",
        "model": "claude-opus-5-5",
        "effects": "simulate",
        "providers": {"anthropic": "fake"},
    }


def test_health_serves_the_same_body_for_cloud_run(client):
    """Cloud Run reserves paths ending in "z", so /healthz 404s there; /health is the live probe."""
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == client.get("/healthz").json()


def test_login_returns_token_only_for_the_right_password(client, auth):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/login", json={"password": "admin"})
    assert r.status_code == 200
    assert f"Bearer {r.json()['token']}" == auth["Authorization"]


def test_request_id_header_and_one_json_log_line(client, capsys):
    r = client.get("/healthz", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    logs = [x for x in lines if "request_id" in x]  # the rest are spans (test_tracing.py)
    assert [(x["request_id"], x["path"], x["status"]) for x in logs] == [
        ("abc123", "/healthz", 200)
    ]
    assert len(logs[0]["trace_id"]) == 32


def test_error_map(store):
    app = create_app(Settings(), store)
    errors = {
        "conflict": ConflictError,
        "missing": NotFound,
        "provider": ProviderNotConfigured,
        "invalid": ValueError,
    }
    for name, exc in errors.items():

        def route(exc=exc):
            raise exc("x")

        app.add_api_route(f"/raise/{name}", route)
    client = TestClient(app)
    got = {name: client.get(f"/raise/{name}").status_code for name in errors}
    assert got == {"conflict": 409, "missing": 404, "provider": 503, "invalid": 422}
    assert client.get("/raise/conflict").json() == {"error": "x"}


def test_local_start_seeds_and_mounts_example_vertical(client, auth):
    assert client.get("/api/example/items").json() == [{"id": "1", "name": "Example item"}]
    assert client.get("/api/example/items/nope").status_code == 404
    item = {"id": "1", "name": "dup"}
    assert client.post("/api/example/items", json=item).status_code == 401
    assert client.post("/api/example/items", json=item, headers=auth).status_code == 409
    new = {"id": "2", "name": "Second"}
    assert client.post("/api/example/items", json=new, headers=auth).status_code == 201


def test_cloud_mode_does_not_seed(store):
    cloud = Settings(mode="cloud", anthropic_api_key="k", admin_password="pw")
    client = TestClient(create_app(cloud, store))
    assert client.get("/api/example/items").json() == []
