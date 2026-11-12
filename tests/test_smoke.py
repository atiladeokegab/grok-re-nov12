"""make smoke is offline and deterministic even when the environment carries a real key."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_smoke_xray_runs_offline_with_a_key_in_the_env(tmp_path):
    env = {
        **os.environ,
        "ANTHROPIC_API_KEY": "sk-ant-a-real-looking-key",
        "XAI_API_KEY": "xai-a-real-looking-key",
        "MODE": "cloud",  # a copied .env may say cloud; the smoke still runs locally
        "EFFECTS": "live",
        "SMOKE_OUT": str(tmp_path),
    }
    done = subprocess.run(
        ["make", "-s", "smoke-xray"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads((tmp_path / "xray.json").read_text())
    assert report["status"] == "done" and report["findings"]
    assert all(f["model"] in ("rules", "fake") for f in report["findings"])
    assert (tmp_path / "store.json").exists()  # the smoke never touches data/store.json
