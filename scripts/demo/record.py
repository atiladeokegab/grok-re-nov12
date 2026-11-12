"""Record the demo film from the offline, seeded app: docs/media/demo.mp4 and demo.gif.

    make demo                                   # installs Chromium once, then records
    uv run scripts/demo/record.py --out /tmp/media --scenes 1
    DEMO_LATENCY=0 uv run scripts/demo/record.py    # effects answer instantly

The app starts the way the e2e tests start it (tests/e2e/app.py), with CASES run, then Chromium
plays SCENES in a 1280x720 window scaled to 1920x1080 (1.5x, legible in the GIF), and ffmpeg makes
an H.264 MP4 (+faststart) and an 8 fps, 640 px GIF. Edit SCENES, not the code below.
DEMO_LATENCY ("low-high" seconds, default 0.35-1.0) makes every simulated effect wait a random
while, so the product grows at a believable pace; only this script passes it to the server, so
smoke and the tests never see it. The latency shows only in a scene that starts work."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # tests/e2e/app.py: one way to start the app, shared with the tests
from tests.e2e.app import serve, stub_fonts  # noqa: E402

CASES = ["001", "002"]  # sample cases run before the camera rolls
# One shot each: (page, what must be on screen before the shot counts, seconds it holds then).
# The film waits on the selector, never on the clock; the hold is screen time for the viewer.
SCENES = [
    ("/", "[data-run]:has-text('Case 001')", 3),
    ("/?theme=refinery", "[data-run]:has-text('Case 002')", 3),
]
# Playwright pads a small viewport into a larger video size, never scales it; ffmpeg scales
# the 1280x720 recording to 1920x1080 instead, so the page reads 1.5x larger.
VIEWPORT = {"width": 1280, "height": 720}
GIF = "fps=8,scale=640:-1:flags=lanczos"


def record(out: Path, scenes: list, latency: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, serve(Path(tmp), CASES, latency) as base:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport=VIEWPORT, record_video_dir=tmp, record_video_size=VIEWPORT
            )
            page = context.new_page()
            stub_fonts(page)
            start, trim = time.monotonic(), None
            for path, selector, hold in scenes:
                page.goto(base + path)
                page.locator(selector).first.wait_for(state="visible")
                if trim is None:  # the film opens on the first finished scene, not a blank page
                    trim = time.monotonic() - start
                page.wait_for_timeout(hold * 1000)
            end = time.monotonic() - start  # the video runs on until close; cut it here
            context.close()  # writes the video file
            webm = page.video.path()
            browser.close()
        mp4, palette = out / "demo.mp4", Path(tmp) / "palette.png"
        h264 = [
            "-vf",
            "scale=1920:1080:flags=lanczos",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "24",
            "-movflags",
            "+faststart",
        ]
        ffmpeg("-ss", f"{trim:.2f}", "-t", f"{end - trim:.2f}", "-i", webm, *h264, mp4)
        ffmpeg("-i", mp4, "-vf", f"{GIF},palettegen", palette)
        ffmpeg("-i", mp4, "-i", palette, "-lavfi", f"{GIF}[x];[x][1:v]paletteuse", out / "demo.gif")
    print(f"{mp4}\n{out / 'demo.gif'}")


def ffmpeg(*args) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "media")
    parser.add_argument("--scenes", type=int, default=len(SCENES), help="record the first N")
    args = parser.parse_args()
    record(args.out, SCENES[: args.scenes], os.environ.get("DEMO_LATENCY", "0.35-1.0"))


if __name__ == "__main__":
    main()
