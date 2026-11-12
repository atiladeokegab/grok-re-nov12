"""X-ray over MCP: three read-only gateway tools (so every call is audited) and GET /api/clients.

xray_listing runs a whole X-ray; explain_finding answers "why?" for a finding or a run's score
from the cited evidence only; get_place_graph is GET /api/place/{id}/graph. A call that came in
over MCP is counted on its run's client_calls.mcp and in the global tally at GET /api/clients.
"""

from fastapi import APIRouter

from starter.core.errors import NotFound
from starter.core.store import Store
from starter.core.xray import FLAG_FACTOR, WEIGHTS, McpCalls
from starter.runtime import mcp_door
from starter.runtime.deps import StoreDep
from starter.verticals import xray

router = APIRouter(tags=["xray"])


@router.get("/api/clients")
def clients(store: StoreDep) -> dict:
    """Every MCP tool call so far, per client: the Grok/Cursor card."""
    return {"mcp": {**McpCalls().model_dump(), **store.snapshot().get("mcp_clients", {})}}


def register_tools(gateway) -> None:
    store = gateway.store

    @gateway.register(effect=False)
    def xray_listing(listing_id_or_url: str, offline: bool = False) -> dict:
        """X-ray a property listing: check its claims against independent sources and return the
        Trust Score, every finding with its cited evidence, and the sources' status. Takes ~10 s.

        Args:
            listing_id_or_url: A listing id ("demo") or the advert's URL.
            offline: Fixtures only, no network (tests and the offline demo).
        """
        report = xray.begin(store, listing_id_or_url, offline)
        if client := mcp_door.CLIENT.get():  # set on the report, so every save keeps it
            setattr(report.client_calls.mcp, client, 1)
        return xray.run_xray(gateway, listing_id_or_url, offline, report).model_dump()

    @gateway.register(effect=False)
    def explain_finding(finding_id: str) -> dict:
        """Explain a finding from its cited evidence only (the claim, each source's value and URL),
        or, given a run_id, explain the Trust Score: each finding that cost points, with sources.

        Args:
            finding_id: A finding id from an X-ray, or an X-ray run_id.
        """
        runs = store.snapshot().get("xray_runs", {})
        if finding_id in runs:
            _count(store, finding_id)
            return explain_score(runs[finding_id])
        latest = set(store.snapshot().get("xray_places", {}).values())
        # shortcut: finding ids repeat across runs; the latest run of each place answers first.
        for run in sorted(runs.values(), key=lambda r: r["run_id"] not in latest):
            for f in run["findings"]:
                if f["id"] == finding_id:
                    _count(store, run["run_id"])
                    return explain(run, f)
        raise NotFound(f"no finding or run {finding_id!r}")

    @gateway.register(effect=False)
    def get_place_graph(place_id: str) -> dict:
        """The evidence graph of a place's latest X-ray: place, claims, evidence, findings, edges.

        Args:
            place_id: The place id from an X-ray report (report.place_id).
        """
        return xray.place_graph(place_id, store)


def _count(store: Store, run_id: str) -> None:
    if client := mcp_door.CLIENT.get():

        def bump(d: dict) -> None:
            mcp = d["xray_runs"][run_id].setdefault("client_calls", {}).setdefault("mcp", {})
            mcp[client] = mcp.get(client, 0) + 1

        store.mutate(bump)


def _v(value, unit) -> str:
    return f"{value} {unit}" if unit else f"{value}"


def explain(run: dict, f: dict) -> dict:
    """The finding, its claim, its cited evidence, and an answer made only from those."""
    claim = next((c for c in run["claims"] if c["id"] == f["claim_id"]), None)
    evidence = [e for e in run["evidence"] if e["id"] in f["evidence_ids"]]
    said = f"The listing says {_v(claim['value'], claim['unit'])}" if claim else "No listing claim"
    parts = [f"{f['field']}: {said}."]
    parts += [
        f"{e['source_name']} says {_v(e['value'], e['unit'])} ({e['source_url'] or 'no URL'})."
        for e in evidence
    ]
    if not evidence:
        parts.append("No source returned evidence for this field.")
    parts.append(f"Verdict: {f['verdict']}, severity {f['severity']}.")
    cited = [
        {k: e[k] for k in ("id", "value", "unit", "source_name", "source_url", "doc_span")}
        for e in evidence
    ]
    return {
        "run_id": run["run_id"],
        "finding": f,
        "claim": claim,
        "evidence": cited,
        "answer": " ".join(parts),
    }


def explain_score(run: dict) -> dict:
    """Why the Trust Score is what it is: each finding that cost points, with its sources."""
    by_id = {e["id"]: e for e in run["evidence"]}
    cost = []
    for f in run["findings"]:
        weight = WEIGHTS[f["severity"]] * (FLAG_FACTOR if f["verdict"] == "flag" else 1)
        if f["verdict"] in ("disagrees", "flag") and weight:
            urls = [by_id[i]["source_url"] for i in f["evidence_ids"] if i in by_id]
            cost.append({**explain(run, f), "weight": weight, "source_urls": urls})
    matches = sum(f["verdict"] == "matches" for f in run["findings"])
    against = sum(c["weight"] for c in cost)
    head = (
        f"Trust Score {run['trust_score']} = round(100 x {matches} matches / "
        f"({matches} + {against:g} weighted disagreements))."
        if run["trust_score"] is not None
        else "No Trust Score: nothing could be checked."
    )
    lines = [f"- {c['answer']} Cost {c['weight']:g}." for c in cost]
    return {
        "run_id": run["run_id"],
        "trust_score": run["trust_score"],
        "counts": run["counts"],
        "costs": cost,
        "answer": "\n".join([head, *lines]),
    }
