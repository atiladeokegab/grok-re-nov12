"""Record the X-ray demo film from a running app: a 1920x1080 MP4 plus a stills contact sheet.

    make dev                                             # in another shell (port 8000)
    uv run python scripts/record_demo.py --out /tmp/film
    uv run python scripts/record_demo.py --url http://127.0.0.1:8123 --out /tmp/film

Beats: open the page, type the demo listing (residential), submit, the fly-in, the Trust Score
and findings streaming in, then one finding opened on its source. Each beat finds its element by
data-testid first and by visible text or role after that, so it survives markup changes. A beat
whose element never appears is logged as missing and the film carries on with what exists.
Chrome runs with SwiftShader so the WebGL fly-in renders on a box without a GPU.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

DEMO_LISTING = "https://www.auctionhouse.co.uk/london/auction/lot/152478"  # 24 Macquarie Way
SIZE = {"width": 1920, "height": 1080}
CHROME = "/usr/bin/google-chrome"
GL_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

# Each target: data-testid first, then role/label/text, then the markup the current UI uses.
LISTING_INPUT = [
    lambda p: p.get_by_test_id("listing-input"),
    lambda p: p.get_by_placeholder(re.compile(r"listing|url|paste", re.I)),
    lambda p: p.get_by_label(re.compile(r"listing", re.I)),
    lambda p: p.locator("#listing, input[name=listing], input[type=url]"),
]
RESIDENTIAL = [
    lambda p: p.get_by_test_id("use-residential"),
    lambda p: p.get_by_role("radio", name=re.compile(r"residential", re.I)),
    lambda p: p.get_by_label(re.compile(r"^residential$", re.I)),
]
SUBMIT = [
    lambda p: p.get_by_test_id("xray-submit"),
    lambda p: p.get_by_role("button", name=re.compile(r"x-ray this listing", re.I)),
    lambda p: p.locator("form button[type=submit]"),
]
FLYIN = [
    lambda p: p.get_by_test_id("flyin"),
    lambda p: p.locator(".xf-root"),
]
SCORE = [
    lambda p: p.get_by_test_id("trust-score"),
    lambda p: p.get_by_text(re.compile(r"trust score", re.I)),
    lambda p: p.locator(".score"),
]
FINDING = [
    lambda p: p.get_by_test_id("finding"),
    lambda p: p.locator("button.finding, .finding[role=button], .finding"),
]
FINDING_SELECTOR = "[data-testid=finding], .finding"
DETAIL = [
    lambda p: p.get_by_test_id("finding-detail"),
    lambda p: p.locator(".finding-detail"),
    lambda p: p.get_by_role("link", name=re.compile(r"source|record|register", re.I)),
]


def find(page: Page, candidates: list, timeout: float) -> Locator | None:
    """The first visible match among the candidates, polled until the timeout; None if absent."""
    deadline = time.monotonic() + timeout
    while True:
        for make in candidates:
            loc = make(page).first
            try:
                if loc.is_visible():
                    return loc
            except Exception:  # a detached or invalid match counts as absent, try the next
                pass
        if time.monotonic() >= deadline:
            return None
        page.wait_for_timeout(250)


class Film:
    def __init__(self, page: Page, stills: Path):
        self.page, self.stills, self.t0, self.beats = page, stills, time.monotonic(), []

    def beat(self, name: str, ok: bool, hold: float, note: str = "") -> None:
        at = round(time.monotonic() - self.t0, 1)
        self.page.wait_for_timeout(hold * 1000)
        shot = self.stills / f"{len(self.beats) + 1:02d}-{name}.png"
        self.page.screenshot(path=shot)
        self.beats.append({"beat": name, "ok": ok, "at_s": at, "note": note, "still": str(shot)})
        print(f"{'ok  ' if ok else 'MISS'} {name:<10} {at:>5}s {note}", flush=True)


def play(page: Page, film: Film, base: str, listing: str) -> None:
    page.goto(base + "/", wait_until="networkidle")
    film.t0 = time.monotonic()  # the film opens on the loaded page, not the blank tab
    film.beat("open", True, 2.5, page.title())

    box = find(page, LISTING_INPUT, 5)
    if box is None:
        film.beat("type", False, 2, "no listing input on this page; recording what exists")
        page.mouse.wheel(0, 600)
        film.beat("page", True, 3, "scrolled the existing page")
        return
    radio = find(page, RESIDENTIAL, 1)
    if radio is not None:
        radio.check()
    box.click()
    box.press_sequentially(listing, delay=25)
    film.beat("type", True, 1.5, f"residential={'set' if radio else 'not found'}")

    button = find(page, SUBMIT, 2)
    if button is None:
        box.press("Enter")
    else:
        button.click()
    fly = find(page, FLYIN, 8)
    if fly is not None:
        try:  # landed (or its fallback card), or the page already disposed of it
            page.wait_for_function(
                "!document.querySelector('.xf-root') || !!document.querySelector('.xf-landed')",
                timeout=20000,
                polling=100,
            )
        except Exception:
            pass
    film.beat("flyin", fly is not None, 2.5, "" if fly else "no fly-in element appeared")

    score = find(page, SCORE, 45)
    film.beat("score", score is not None, 3, score.inner_text()[:60] if score else "no score")

    first = find(page, FINDING, 30)
    count = page.locator(FINDING_SELECTOR).count() if first is not None else 0
    film.beat("findings", first is not None, 3.5, f"{count} visible")
    if first is None:
        return
    first.scroll_into_view_if_needed()
    first.click()
    detail = find(page, DETAIL, 8)
    if detail is not None:
        detail.scroll_into_view_if_needed()
    film.beat("source", detail is not None, 5, "" if detail else "no evidence detail opened")


def ffmpeg(*args) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the running app")
    ap.add_argument("--listing", default=DEMO_LISTING, help="what to type into the listing field")
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "xray-demo")
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed; apt install ffmpeg")
    stills = args.out / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    base = args.url.rstrip("/")

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        exe = CHROME if Path(CHROME).exists() else None  # else Playwright's own Chromium
        browser = p.chromium.launch(executable_path=exe, args=GL_ARGS)
        context = browser.new_context(
            viewport=SIZE, record_video_dir=tmp, record_video_size=SIZE, device_scale_factor=1
        )
        page = context.new_page()
        start = time.monotonic()
        film = Film(page, stills)
        try:
            play(page, film, base, args.listing)
        finally:
            trim = film.t0 - start  # cut the blank tab before the first page arrives
            end = time.monotonic() - start
            context.close()  # writes the video
            webm = page.video.path()
            browser.close()
        mp4 = args.out / "xray-demo.mp4"
        h264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart"]
        ffmpeg("-ss", f"{trim:.2f}", "-t", f"{end - trim:.2f}", "-i", webm, *h264, mp4)

    length = duration(mp4)
    sheet = args.out / "contact-sheet.png"
    # 12 frames evenly across the film, 4x3 at 480 px wide each.
    ffmpeg("-i", mp4, "-vf", f"fps=12/{length:.2f},scale=480:-1,tile=4x3", "-frames:v", 1, sheet)
    summary = {"video": str(mp4), "seconds": round(length, 1), "sheet": str(sheet)}
    (args.out / "beats.json").write_text(json.dumps({**summary, "beats": film.beats}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
