"""Score the lease extractor against the organisers' hand-labelled MCL gold set.

LEASES_DIR: folder of MCL .docx templates; LEASE_LABELS: labelled-leases-and-clauses.csv.
Writes docs/lease-eval.md and docs/lease-eval.json. Exits 0 with a message when the data is
absent (CI has none; the templates and labels stay outside the repo).
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starter.verticals.lease import FIELDS, abstract  # noqa: E402

CACHE = Path.home() / "hub/projects/grok-re-nov12/data-cache"
LEASES_DIR = Path(os.environ.get("LEASES_DIR", CACHE / "leases/Official and public leases"))
LABELS = Path(
    os.environ.get("LEASE_LABELS", CACHE / "leases-labelled/labelled-leases-and-clauses.csv")
)
DOCS = Path(__file__).resolve().parents[1] / "docs"
THRESHOLD = 0.5
# Function words plus the labellers' own vocabulary about the template, which no lease contains.
STOP = set(
    """the and for with from that this which are its any all also plus into under named
    defined means same pattern present placeholder placeholders optional template square
    bracket brackets alternatives left blank there here been each other see""".split()
)

RULE = f"""\
- Gold is **placeholder** when the label starts with "Placeholder"; **absent** when it starts
  with "Not " or "No "; **optional** when it starts with "Optional"; **present** when it starts
  with "Yes".
- Absent gold is correct when the extractor finds nothing (or only an optional clause).
- Optional gold is correct when the extractor finds nothing or marks the clause optional
  (it was bracketed in the template).
- Present gold is correct when the extractor finds the clause.
- Otherwise, content words of the gold label (lower-case, 3+ letters, minus function words
  and template-describing words such as "placeholder", "optional", "present") must be
  ≥{THRESHOLD:.0%} present in the extracted value plus the heading it came from.
- **Strict** also requires the placeholder flag to equal (gold is placeholder), as briefed.
  **Content** requires the flag only when gold is placeholder: the non-placeholder gold labels
  describe templates (for example parties "named in LR3") whose text still holds [LANDLORD]
  blanks, so a strict mismatch there says more about the label than the extractor."""


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3} - STOP


def score(gold: str, got: dict) -> tuple[bool, bool]:
    """(strict, content) correctness of one extracted field against one gold label."""
    g = gold.strip()
    found = got["value"] is not None
    if g.startswith(("Not ", "No ", "No—", "No —")):
        ok = not found or got["optional"]
        return ok, ok
    if g.startswith("Optional"):
        ok = not found or got["optional"]
        return ok, ok
    if g.startswith("Yes"):
        return found, found
    gold_ph = g.lower().startswith("placeholder")
    gw = words(g)
    overlap = found and len(gw & words(f"{got['value']} {got['source']}")) >= THRESHOLD * len(gw)
    flag_ok = got["placeholder"] == gold_ph
    return bool(overlap and flag_ok), bool(overlap and (flag_ok or not gold_ph))


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> int:
    if not LABELS.exists() or not LEASES_DIR.is_dir():
        print(f"lease data not present ({LABELS} / {LEASES_DIR}); nothing to score")
        return 0
    docx = {key(p.stem): p for p in LEASES_DIR.glob("*.docx")}
    rows = [r for r in csv.DictReader(LABELS.open(encoding="utf-8")) if r["level"] == "document"]
    per = {f: {"n": 0, "strict": 0, "content": 0} for f in FIELDS}
    docs, skipped = [], []
    for r in rows:
        path = docx.get(key(r["sample_id"]))
        if not path:
            skipped.append(r["sample_id"])
            continue
        got = abstract(path)
        result = {}
        for f in FIELDS:
            strict, content = score(r[f], got[f])
            per[f]["n"] += 1
            per[f]["strict"] += strict
            per[f]["content"] += content
            result[f] = {
                "strict": strict,
                "content": content,
                "placeholder": got[f]["placeholder"],
                "source": got[f]["source"],
                "doc_span": (got[f]["doc_span"] or "")[:80] or None,
            }
        docs.append({"sample_id": r["sample_id"], "file": path.name, "fields": result})

    n = sum(v["n"] for v in per.values())
    total = {k: sum(v[k] for v in per.values()) for k in ("strict", "content")}
    out = {
        "documents": len(docs),
        "skipped_no_docx": skipped,
        "threshold": THRESHOLD,
        "fields": per,
        "overall": {"n": n, **total},
        "per_document": docs,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "lease-eval.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    def pct(a: int, b: int) -> str:
        return f"{a / b:.0%}" if b else "-"

    lines = [
        "# Lease abstraction: per-field accuracy",
        "",
        f"`scripts/eval_leases.py` (`make eval-leases`) over the {len(docs)} document-level rows",
        "of the organisers' hand-labelled Model Commercial Lease gold set whose .docx we hold.",
        "The extractor is `starter/verticals/lease.py`: deterministic heading and definition",
        "rules over the Word paragraphs, no model.",
        "",
        "| field | n | strict correct | strict | content correct | content |",
        "|---|---|---|---|---|---|",
    ]
    for f, v in per.items():
        lines.append(
            f"| {f} | {v['n']} | {v['strict']} | {pct(v['strict'], v['n'])} "
            f"| {v['content']} | {pct(v['content'], v['n'])} |"
        )
    lines.append(
        f"| **overall** | {n} | {total['strict']} | **{pct(total['strict'], n)}** "
        f"| {total['content']} | **{pct(total['content'], n)}** |"
    )
    lines += ["", "## Scoring rule", "", RULE, "", "## Skipped", ""]
    lines.append(
        "- Rent-roll variance: the gold set holds unused templates with no real rent figures, "
        "so there is nothing to reconcile a rent roll against."
    )
    lines.append(
        "- Clause-level rows (MCL-LEASECLAUSE-*, licences, HMLR-LR1..LR14) are not scored here."
    )
    if skipped:
        lines.append(f"- Document rows with no matching .docx: {', '.join(skipped)}.")
    lines += [
        "",
        "## Caveats",
        "",
        f"- In-sample: {len(docs)} documents, all MCL templates from one drafting group, and the",
        "  rules were written while reading these same templates. There is no held-out set, so",
        "  read this as a 15-template gold-set score, not accuracy on arbitrary executed leases.",
        "- The Legal-lease_datasets zips (CUAD/DocLayNet) are not UK leases and are not used.",
        "- Per-document results and short source spans: `docs/lease-eval.json`.",
    ]
    (DOCS / "lease-eval.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[6 : 9 + len(per) + 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
