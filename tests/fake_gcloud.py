"""Run a script in scripts/ against fake `gcloud`, `curl` and `uv` first on PATH. Each fake records
its arguments (and the environment the scripts hand it) to a log and answers with canned values, so
the real shell runs end to end without a cloud, a network or a project."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://hackathon-starter-123456.europe-west1.run.app"
REVISION = "hackathon-starter-00002-abc"

FAKE = """#!{python}
import json, os, re, sys

name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
call = {{"cmd": name, "args": args}}
for var in ("CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT", "BASE_URL", "ADMIN_PASSWORD"):
    if var in os.environ:
        call[var] = os.environ[var]
if "--data-file=-" in args:
    call["stdin"] = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(call) + "\\n")

line = " ".join([name, *args])
if os.environ.get("FAKE_FAIL") and os.environ["FAKE_FAIL"] in line:
    sys.exit(1)
if name != "gcloud":
    sys.exit(0)
exists = os.environ.get("FAKE_EXISTING") == "1"
fmt = next((a.split("=", 1)[1] for a in args if a.startswith("--format=")), "")
if "--format" in args:
    fmt = args[args.index("--format") + 1]
fields = {{
    "projectNumber": "123456",
    "status.url": "{url}",
    "status.latestReadyRevisionName": "{revision}",
}}
if args[:2] == ["config", "get-value"]:
    print("me@example.com")
elif args[:2] == ["services", "list"]:
    if exists:
        print("\\n".join(os.environ["FAKE_APIS"].split()))
elif args[:3] == ["secrets", "versions", "access"]:
    print("live-pw", end="")
elif "describe" in args and (m := re.match(r"value\\((.*)\\)", fmt)):
    print("\\t".join(fields[f] for f in m.group(1).split(",")))
elif "describe" in args and not exists:
    print("ERROR: NOT_FOUND", file=sys.stderr)
    sys.exit(1)
"""


def run(script: str, tmp: Path, env: dict[str, str], *, dirty=False, scripts=ROOT / "scripts"):
    """Runs scripts/<script> from a fresh one-commit git repo in tmp; returns (process, calls)."""
    bin_dir, repo, log = tmp / "bin", tmp / "repo", tmp / "calls.jsonl"
    bin_dir.mkdir()
    fake = FAKE.format(python=sys.executable, url=URL, revision=REVISION)
    for name in ("gcloud", "curl", "uv"):
        (bin_dir / name).write_text(fake)
        (bin_dir / name).chmod(0o755)
    repo.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=repo, check=True)
    if dirty:
        (repo / "uncommitted.py").write_text("")
    # A bare environment: no real credentials, project or impersonation leak in from the caller.
    base = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp), "FAKE_LOG": str(log)}
    proc = subprocess.run(
        ["bash", str(scripts / script)],
        cwd=repo,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    calls = [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    return proc, calls


def head(tmp: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=tmp / "repo",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
