"""The Cursor SDK step: a Cursor agent writes the plain-English summary of an X-ray's
findings, citing evidence ids only (tools/cursor-step). Off without CURSOR_API_KEY."""

import json
import os
import subprocess
import time
from pathlib import Path

STEP = Path(__file__).resolve().parents[2] / "tools" / "cursor-step" / "index.ts"
CALLS = {"count": 0, "ms": 0}  # every attempted call, for client_calls.cursor_sdk


def summarize(report: dict) -> dict | None:
    """{"summary", "evidence_ids", "model", "ms"}, or None with no key or on any failure."""
    if not os.environ.get("CURSOR_API_KEY"):
        return None
    start = time.perf_counter()
    try:
        out = subprocess.run(
            ["node", str(STEP)],
            input=json.dumps(report),
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
            cwd=STEP.parent,
        )
        result = json.loads(out.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None  # a summary is optional; a failed one never fails the X-ray
    finally:
        CALLS["count"] += 1
        CALLS["ms"] += round((time.perf_counter() - start) * 1000)
    known = {e["id"] for e in report.get("evidence", [])}
    if not isinstance(result.get("summary"), str):
        return None
    # the model's output is untrusted: keep only citations of evidence this report holds
    result["evidence_ids"] = [i for i in result.get("evidence_ids", []) if i in known]
    return result
