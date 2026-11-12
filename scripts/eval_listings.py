"""Reproducible listing evaluation. Unknown labels never become clean negatives."""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

SEED = "grok-re-nov12:independent-eval:v1"
VERDICTS = {"matches", "disagrees", "flag", "unverifiable"}
POSITIVE = {"disagrees", "flag"}


def select_listings(path: Path, count: int = 20) -> dict:
    if count < 1:
        raise ValueError("sample count must be positive")
    content = path.read_bytes()
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if any(not row.get("listing_id") for row in rows):
        raise ValueError("every crawl row requires a listing_id")
    ids = {row["listing_id"] for row in rows}
    ordered = sorted(ids, key=lambda lid: hashlib.sha256(f"{SEED}:{lid}".encode()).hexdigest())
    return {
        "schema_version": 1,
        "seed": SEED,
        "crawl_sha256": hashlib.sha256(content).hexdigest(),
        "selection": "First IDs ordered by SHA256(seed + colon + listing_id); deduplicated",
        "listing_ids": ordered[:count],
    }


def refuse_tuning_ids(listing_ids: list[str], manifest: dict) -> None:
    overlap = set(listing_ids) & set(manifest["listing_ids"])
    if overlap:
        raise ValueError("held-out listing ids cannot be used for tuning")


def score_reports(manifest: dict, reports: list[dict], labels: list[dict]) -> dict:
    ids = manifest["listing_ids"]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate listing ids in evaluation manifest")
    selected = set(ids)
    predictions = defaultdict(set)
    sources = defaultdict(Counter)
    listing_scores = {}
    run_errors = {}
    ungrounded_findings = 0
    ungrounded_flags = 0
    for report in reports:
        lid = report["listing_id"]
        if lid not in selected:
            raise ValueError("report contains a listing outside the frozen sample")
        if lid in listing_scores:
            raise ValueError("more than one report for an evaluation listing")
        listing_scores[lid] = report.get("trust_score")
        if report.get("error"):
            run_errors[lid] = report["error"]
        evidence = {row["id"]: row for row in report.get("evidence", [])}
        if len(evidence) != len(report.get("evidence", [])):
            raise ValueError("duplicate evidence id in report")
        for source in report.get("sources", []):
            if source["status"] == "ok" and source.get("n_evidence", 0) > 0:
                sources[source["name"]]["checked"] += 1
            else:
                sources[source["name"]]["unverifiable"] += 1
        for finding in report.get("findings", []):
            verdict = finding["verdict"]
            if verdict not in VERDICTS:
                raise ValueError("unrecognised finding verdict")
            cited = finding.get("evidence_ids", [])
            agents = {evidence[eid]["agent"] for eid in cited if eid in evidence}
            if verdict == "unverifiable" and not cited:
                continue
            if (
                not cited
                or any(eid not in evidence for eid in cited)
                or not agents
                or any(
                    not (evidence[eid].get("source_url") or evidence[eid].get("doc_span"))
                    for eid in cited
                )
            ):
                ungrounded_findings += 1
                ungrounded_flags += verdict in POSITIVE
                continue
            for agent in agents:
                predictions[(lid, agent, finding["field"])].add(verdict)
                sources[agent][verdict] += 1

    matrix = Counter(tp=0, fn=0, fp=0, tn=0)
    labelled = set()
    unresolved_labels = 0
    for label in labels:
        key = (label["listing_id"], label["source"], label["field"])
        if key[0] not in selected or key in labelled:
            raise ValueError("label is outside the sample or duplicated")
        source_url = urlsplit(label.get("source_url", ""))
        if (
            source_url.scheme not in ("http", "https")
            or not source_url.netloc
            or not label.get("reason")
        ):
            raise ValueError("independent labels require a source URL and reason")
        expected = label["expected"]
        if expected not in VERDICTS:
            raise ValueError("unrecognised expected verdict")
        labelled.add(key)
        actual = predictions.get(key, set())
        if expected == "unverifiable":
            unresolved_labels += 1
            continue
        positive = bool(actual & POSITIVE)
        if expected in POSITIVE:
            matrix["tp" if positive else "fn"] += 1
        elif positive:
            matrix["fp"] += 1
            sources[key[1]]["false_flags"] += 1
        elif "matches" in actual:
            matrix["tn"] += 1
        else:
            # Abstention on a negative is not a successful clean check.
            unresolved_labels += 1

    positives = matrix["tp"] + matrix["fn"]
    negatives = matrix["fp"] + matrix["tn"]
    unresolved_flags = ungrounded_flags
    unresolved_flags += sum(bool(v & POSITIVE) for k, v in predictions.items() if k not in labelled)
    unresolved_flags += sum(
        bool(predictions.get((r["listing_id"], r["source"], r["field"]), set()) & POSITIVE)
        for r in labels
        if r["expected"] == "unverifiable"
    )
    return {
        "selected_listings": len(ids),
        "reported_listings": len(listing_scores),
        "missing_reports": sorted(selected - listing_scores.keys()),
        "run_errors": run_errors,
        "ungrounded_findings": ungrounded_findings,
        "listing_scores": listing_scores,
        "per_source": {key: dict(value) for key, value in sorted(sources.items())},
        "labelled_comparisons": len(labels),
        "insufficient_evidence_labels": unresolved_labels,
        "unresolved_flags": unresolved_flags,
        "confusion_matrix": dict(matrix),
        "confirmed_discrepancies": positives,
        "confirmed_negative_comparisons": negatives,
        "detection_rate": matrix["tp"] / positives if positives else None,
        "false_positive_rate": matrix["fp"] / negatives if negatives else None,
        "measurement_note": "Rates are unavailable without independently confirmed denominators. "
        "Source checked/unverifiable counts are listing/source runs; verdict "
        "counts are findings. Missing or ungrounded citations remain unresolved. "
        "This sample does not establish population accuracy.",
    }


def print_table(result: dict) -> None:
    print("source                 checked_runs  disagrees  unverifiable_runs  false_flags")
    for name, row in result["per_source"].items():
        print(
            f"{name:22} {row.get('checked', 0):7} {row.get('disagrees', 0):10} "
            f"{row.get('unverifiable', 0):13} {row.get('false_flags', 0):12}"
        )
    print(
        f"Listings: {result['reported_listings']}/{result['selected_listings']} reports; "
        f"{len(result['run_errors'])} run errors; "
        f"{result['ungrounded_findings']} ungrounded findings; "
        f"{result['unresolved_flags']} unresolved flags"
    )
    for lid, score in result["listing_scores"].items():
        print(f"{lid}: Trust Score {score if score is not None else 'unverifiable'}")
    matrix = result["confusion_matrix"]
    if result["detection_rate"] is None:
        print("Detection rate unavailable: no independently confirmed discrepancies.")
    else:
        print(
            f"Caught {matrix['tp']} of {result['confirmed_discrepancies']} confirmed discrepancies."
        )
    if result["false_positive_rate"] is None:
        print("False-positive rate unavailable: no independently confirmed negative comparisons.")
    else:
        print(
            f"False flags: {matrix['fp']}/{result['confirmed_negative_comparisons']} "
            "confirmed negative comparisons."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("csv", type=Path)
    sample.add_argument("--count", type=int, default=20)
    sample.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run", help="run the actual pipeline on the frozen sample")
    run.add_argument("manifest", type=Path)
    run.add_argument("csv", type=Path)
    run.add_argument(
        "--out",
        type=Path,
        required=True,
        help="new directory for reports and isolated store",
    )
    score = commands.add_parser("score")
    score.add_argument("manifest", type=Path)
    score.add_argument("reports", type=Path, help="JSON array of actual XRayReport outputs")
    score.add_argument(
        "--labels", type=Path, help="Independent field/source labels; never predictions"
    )
    score.add_argument("--out", type=Path)
    tuning = commands.add_parser("check-tuning")
    tuning.add_argument("manifest", type=Path)
    tuning.add_argument("listing_ids", nargs="+")
    args = parser.parse_args()
    if args.command == "sample":
        result = select_listings(args.csv, args.count)
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(f"Frozen {len(result['listing_ids'])} ids; crawl SHA256 {result['crawl_sha256']}")
    elif args.command == "check-tuning":
        refuse_tuning_ids(args.listing_ids, json.loads(args.manifest.read_text()))
        print("No held-out ids in tuning inputs.")
    elif args.command == "run":
        manifest = json.loads(args.manifest.read_text())
        actual_hash = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        if actual_hash != manifest["crawl_sha256"]:
            parser.error("crawl checksum differs from frozen sample manifest")
        if args.out.exists():
            parser.error(f"output directory already exists: {args.out}")
        args.out.mkdir(parents=True)
        # Use the same engine as scripts/xray.py and an isolated store; the command is explicit
        # because live listing/EPC/search calls consume provider quota.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        os.environ["LISTINGS_CSV"] = str(args.csv.resolve())
        from starter.core.gateway import build_gateway
        from starter.core.store import open_store
        from starter.runtime.config import Settings
        from starter.verticals.xray import run_xray

        with TemporaryDirectory(prefix="xray-eval-") as temporary:
            settings = Settings.from_env(
                {
                    **os.environ,
                    "MODE": "local",
                    "STORE": "json",
                    "DATA_PATH": str(Path(temporary) / "store.json"),
                    "EFFECTS": "simulate",
                }
            )
            gateway = build_gateway(open_store(settings.data_path), settings.mode_effects)
            reports = []
            for index, listing_id in enumerate(manifest["listing_ids"], 1):
                print(f"[{index}/{len(manifest['listing_ids'])}] {listing_id}", flush=True)
                try:
                    reports.append(run_xray(gateway, listing_id).model_dump())
                except Exception as error:
                    reports.append(
                        {
                            "listing_id": listing_id,
                            "status": "error",
                            "error": f"{type(error).__name__}: {error}",
                            "sources": [],
                            "findings": [],
                            "evidence": [],
                            "trust_score": None,
                        }
                    )
            (args.out / "reports.json").write_text(json.dumps(reports, indent=2) + "\n")
            print(f"Wrote {len(reports)} actual pipeline reports to {args.out / 'reports.json'}")
    else:
        labels = json.loads(args.labels.read_text()) if args.labels else []
        result = score_reports(
            json.loads(args.manifest.read_text()),
            json.loads(args.reports.read_text()),
            labels,
        )
        print_table(result)
        if args.out:
            args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
