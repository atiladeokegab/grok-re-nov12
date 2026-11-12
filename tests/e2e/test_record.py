"""The demo recorder end to end: one scene, offline app, Chromium, ffmpeg. Run by `make e2e`."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e.app import ROOT

pytestmark = pytest.mark.e2e


def test_recorder_writes_an_mp4(tmp_path, browser_type):
    if not shutil.which("ffmpeg") or not Path(browser_type.executable_path).exists():
        pytest.skip("needs ffmpeg and Playwright Chromium")
    cmd = [sys.executable, ROOT / "scripts/demo/record.py", "--out", tmp_path, "--scenes", "1"]
    subprocess.run(cmd, check=True, timeout=180)
    mp4 = tmp_path / "demo.mp4"
    assert mp4.exists() and mp4.stat().st_size > 0
