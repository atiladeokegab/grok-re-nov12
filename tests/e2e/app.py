"""The app the way `make dev` starts it (offline, seeded) on a free port, with sample cases already
run. Shared by the e2e tests and scripts/demo/record.py, so the film shows what the tests check."""

import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2

ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def serve(
    tmp: Path, cases: list[str], demo_latency: str = "", password: str = "admin"
) -> Iterator[str]:
    """Yields the base URL. demo_latency is DEMO_LATENCY for this server only: set explicitly, so a
    value in the caller's shell never reaches the tests."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "ANTHROPIC_API_KEY": "",
        "MODE": "local",
        "EFFECTS": "simulate",
        "DATA_PATH": str(tmp / "store.json"),
        "DEMO_LATENCY": demo_latency,
        "ADMIN_PASSWORD": password,
    }
    log = open(tmp / "server.log", "w")  # closed in the finally below
    cmd = [sys.executable, "-m", "uvicorn", "starter.main:app", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(base, proc, tmp / "server.log")
        token = httpx2.post(f"{base}/api/login", json={"password": password}).json()["token"]
        for case in cases:
            body = (ROOT / "cases" / "sample" / case / "index.md").read_text()
            run = httpx2.post(
                f"{base}/api/runs",
                json={"id": case, "body": body},
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            run.raise_for_status()
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


def _wait_healthy(base: str, proc: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            if httpx2.get(f"{base}/health", timeout=1).status_code == 200:
                return
        except httpx2.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"the app did not come up on {base}:\n{log.read_text()[-2000:]}")


def stub_fonts(page) -> None:
    """Web fonts answer empty CSS, so the page stays offline and a missing network is no error."""
    stub = {"status": 200, "content_type": "text/css", "body": ""}
    page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(**stub))
    page.route("https://fonts.gstatic.com/**", lambda route: route.fulfill(**stub))
