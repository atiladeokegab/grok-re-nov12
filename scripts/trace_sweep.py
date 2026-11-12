"""Count tool errors by (tool, error) across every case of a run, from ANSWERS/<case>/trace.jsonl.

    uv run scripts/trace_sweep.py ANSWERS

The same error in 3 or more cases is a system bug, not a case problem: the exit code is then 1.
No trace.jsonl at all exits 2, so a wrong folder never reads as a clean sweep.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

NOISE = re.compile(r"input_value=.*?, input_type=\w+|For further information visit \S+")


def normalise(error: str) -> str:
    # ponytail: strips pydantic's per-call values only; add a pattern when another tool's
    # messages carry ids or timestamps that split one bug into many rows.
    return " ".join(NOISE.sub("", error).split())


def sweep(answers: Path) -> tuple[Counter, Counter, int]:
    """(cases, calls, traces): per (tool, error), how many cases hit it and how many times."""
    cases: Counter = Counter()
    calls: Counter = Counter()
    traces = sorted(answers.glob("*/trace.jsonl"))
    for trace in traces:
        seen = set()
        for line in trace.read_text().splitlines():
            entry = json.loads(line)
            if entry.get("tool") and entry.get("status") == "ERROR":
                key = (entry["tool"], normalise(entry.get("error") or ""))
                calls[key] += 1
                seen.add(key)
        cases.update(seen)
    return cases, calls, len(traces)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("answers", type=Path)
    args = parser.parse_args(argv)
    cases, calls, traces = sweep(args.answers)
    if not traces:
        print(f"no trace.jsonl under {args.answers}")
        return 2
    if not cases:
        print(f"no tool errors in {traces} traces")
        return 0
    print(f"{'cases':>5} {'calls':>5}  tool: error   ({traces} traces)")
    for (tool, error), n in cases.most_common():
        print(f"{n:>5} {calls[tool, error]:>5}  {tool}: {error}")
    systemic = sum(n >= 3 for n in cases.values())
    if systemic:
        print(f"{systemic} error(s) in 3+ cases: fix the tool or the prompt, not the cases")
    return 1 if systemic else 0


if __name__ == "__main__":
    sys.exit(main())
