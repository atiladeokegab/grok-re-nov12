"""POST /api/xray budget: the route is open and a live run can cost model calls.

A sliding window per client IP (XRAY_PER_IP_PER_MIN, default 6) and over everyone
(XRAY_GLOBAL_PER_MIN, default 30); over either, 429 with Retry-After. A repeat of the demo listing
within 10 minutes of a finished demo run gets that run back, uncounted. MCP's xray_listing is
authenticated and not throttled here.
"""

import math
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

WINDOW = 60.0
DEMO_TTL = 600.0
_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)  # ip, or "*" for everyone -> times
_demo: dict[tuple, tuple[str, float]] = {}  # (offline, use) -> (run_id, started)


def reset() -> None:
    with _lock:
        _hits.clear()
        _demo.clear()


def client_ip(request: Request) -> str:
    # shortcut: trusts X-Forwarded-For's first hop (Cloud Run's proxy sets it, but a client can
    # also send one); use the last untrusted hop if someone starts spoofing it.
    if fwd := request.headers.get("x-forwarded-for"):
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(request: Request) -> None:
    """Count this run against both windows, or raise 429 without counting it."""
    # shortcut: in-process, so each Cloud Run instance has its own budget; move to the store
    # if the service scales past a couple of instances.
    limits = {
        client_ip(request): int(os.environ.get("XRAY_PER_IP_PER_MIN", "6")),
        "*": int(os.environ.get("XRAY_GLOBAL_PER_MIN", "30")),
    }
    now = time.monotonic()
    with _lock:
        full = {}  # key -> seconds until its oldest hit leaves the window
        for key, limit in limits.items():
            q = _hits[key]
            while q and q[0] <= now - WINDOW:
                q.popleft()
            if len(q) >= limit:
                full[key] = q[0] + WINDOW - now
        if full:
            n = max(1, math.ceil(max(full.values())))
            who = "right now" if "*" in full else "from you right now"
            raise HTTPException(
                429,
                f"Too many X-rays {who}. Try again in {n} s, or open the demo listing.",
                headers={"Retry-After": str(n)},
            )
        for key in limits:
            _hits[key].append(now)


def _demo_key(body) -> tuple | None:
    return (body.offline, body.use) if body.listing_id == "demo" else None


def cached_demo(store, body) -> str | None:
    """The run_id of a done demo run started within DEMO_TTL with the same options, else None."""
    key = _demo_key(body)
    with _lock:
        hit = _demo.get(key) if key else None
    if not hit or time.monotonic() - hit[1] > DEMO_TTL:
        return None
    run = store.snapshot().get("xray_runs", {}).get(hit[0])
    return hit[0] if run and run.get("status") == "done" else None


def remember_demo(body, run_id: str) -> None:
    if key := _demo_key(body):
        with _lock:
            _demo[key] = (run_id, time.monotonic())
