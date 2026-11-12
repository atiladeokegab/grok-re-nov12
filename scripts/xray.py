"""One X-ray, JSON out.

    uv run python scripts/xray.py <listing-id | advert url>   # live sources
    uv run python scripts/xray.py --fixture demo              # offline, fixtures only

Exit code 0 when the run finished with a score and at least one finding per source that
returned evidence; 1 otherwise (make smoke gates on it).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starter.core.gateway import build_gateway  # noqa: E402
from starter.core.store import open_store  # noqa: E402
from starter.runtime.config import Settings  # noqa: E402
from starter.verticals.xray import run_xray  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ref", nargs="?", help="crawl listing id or advert URL")
    p.add_argument("--fixture", help="run offline on this fixture (e.g. demo)")
    args = p.parse_args(argv)
    if not (args.ref or args.fixture):
        p.error("give a listing id, a URL or --fixture")
    settings = Settings.from_env()
    gateway = build_gateway(open_store(settings.data_path), settings.mode_effects)
    report = run_xray(gateway, args.fixture or args.ref, offline=bool(args.fixture))
    print(json.dumps(report.model_dump(), indent=1))
    agent = {e.id: e.agent for e in report.evidence}
    by_source = {agent.get(i) for f in report.findings for i in f.evidence_ids}
    with_evidence = {s.name for s in report.sources if s.n_evidence}
    ok = (
        report.status == "done"
        and report.findings
        and all(s in by_source or s == "listing_history" for s in with_evidence)
    )
    print(
        f"trust_score={report.trust_score} counts={report.counts.model_dump()} "
        f"sources={[(s.name, s.status, s.ms) for s in report.sources]}",
        file=sys.stderr,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
