"""The post-deploy smoke, without a network: the live-marked tests run against a real server on
loopback the way scripts/deploy.sh runs them against Cloud Run, and the server's own request log
proves they talked to it rather than to an in-process app."""

import json
import os
import subprocess
import sys

from tests.e2e.app import ROOT, serve


def test_live_tests_sweep_the_server_at_base_url(tmp_path):
    with serve(tmp_path, [], password="live-pw") as base:
        env = {**os.environ, "BASE_URL": base, "ADMIN_PASSWORD": "live-pw"}
        cmd = [sys.executable, "-m", "pytest", "-q", "-m", "live", "-p", "no:cacheprovider"]
        done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = [ln for ln in (tmp_path / "server.log").read_text().splitlines() if ln.startswith("{")]
    requests = [r for r in map(json.loads, lines) if "method" in r]  # not the span lines
    hits = {(r["method"], r["path"], r["status"]) for r in requests}
    assert ("GET", "/", 200) in hits and ("GET", "/api/example/items", 200) in hits
    assert ("POST", "/api/runs", 401) in hits
    assert ("POST", "/api/mcp/token", 200) in hits  # the token came from ADMIN_PASSWORD
