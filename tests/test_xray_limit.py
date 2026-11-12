"""POST /api/xray is budgeted per client IP and globally; a demo repeat reuses its done run."""

import time

from fastapi.testclient import TestClient

from starter.runtime.config import Settings
from starter.runtime.factory import create_app


def _post(client, ip: str, ref: str = "nope"):
    # an unknown listing still counts against the budget (404 after the check), and starts no run
    body = {"listing_id": ref, "offline": True}
    return client.post("/api/xray", json=body, headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"})


def test_the_seventh_run_from_one_ip_is_429_and_another_ip_still_passes(tmp_path):
    with TestClient(create_app(Settings(data_path=str(tmp_path / "s.json")))) as client:
        assert [_post(client, "1.1.1.1").status_code for _ in range(6)] == [404] * 6
        r = _post(client, "1.1.1.1")
        assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 60
        assert "Too many X-rays from you right now" in r.json()["detail"]
        assert _post(client, "2.2.2.2").status_code == 404


def test_the_global_cap_holds_across_ips(tmp_path, monkeypatch):
    monkeypatch.setenv("XRAY_GLOBAL_PER_MIN", "3")
    with TestClient(create_app(Settings(data_path=str(tmp_path / "s.json")))) as client:
        assert [_post(client, f"9.9.9.{i}").status_code for i in range(3)] == [404] * 3
        r = _post(client, "8.8.8.8")
        assert r.status_code == 429 and "Retry-After" in r.headers


def test_a_demo_repeat_returns_the_done_run_without_counting(tmp_path, monkeypatch):
    monkeypatch.setenv("XRAY_PER_IP_PER_MIN", "1")
    with TestClient(create_app(Settings(data_path=str(tmp_path / "s.json")))) as client:
        first = _post(client, "3.3.3.3", "demo")
        assert first.status_code == 202
        run_id = first.json()["run_id"]
        for _ in range(50):
            if client.get(f"/api/xray/{run_id}").json()["status"] != "running":
                break
            time.sleep(0.1)
        again = [_post(client, "3.3.3.3", "demo") for _ in range(3)]  # over its budget of 1
        assert {(r.status_code, r.json()["run_id"]) for r in again} == {(202, run_id)}
