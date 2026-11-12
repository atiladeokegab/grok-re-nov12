"""X-ray: one listing in, a Trust Score and sourced findings out.

POST /api/xray {listing_id | url} starts a run in a thread and returns {run_id};
GET /api/xray/{run_id} is the XRayReport; GET /api/xray/{run_id}/events streams it (SSE) as it
grows: `source`, `claim`, `evidence`, `finding`, `history`, `score`, then `done` (terminal; also
sent on error, with status "error"). Each event's data is the full object.
GET /api/place/{id}/graph is the evidence graph of the latest run for that place.

Each source agent runs as a read-only gateway tool `source_<name>`, so every call is audited.
"""

import asyncio
import json
import threading
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from starter.core.errors import NotFound
from starter.core.store import Store
from starter.core.xray import (
    Claim,
    Evidence,
    HistoryEntry,
    Photo,
    PlaceView,
    SourceStatus,
    XRayReport,
    count,
    trust_score,
)
from starter.runtime.deps import StoreDep
from starter.verticals import reconcile as rec
from starter.verticals.narrate import narrate
from starter.verticals.sources import SOURCES, load_listing

router = APIRouter(tags=["xray"])
_ctx: dict[str, tuple] = {}  # run_id -> (place, listing) while its sources run


class XRayRequest(BaseModel):
    listing_id: str | None = None
    url: str | None = None
    offline: bool = False  # fixtures only, no network: what make smoke runs
    use: Literal["residential", "office"] | None = None  # None: as the listing says


def register_tools(gateway) -> None:
    for module in SOURCES:
        gateway.register(_source_tool(module), effect=False)


def _source_tool(module):
    def tool(run_id: str) -> dict:
        place, listing = _ctx[run_id]
        claims, evidence = module.ingest(place, listing)
        return {
            "claims": [c.model_dump() for c in claims],
            "evidence": [e.model_dump() for e in evidence],
        }

    tool.__name__ = f"source_{module.NAME}"
    tool.__doc__ = (
        f"Run the {module.NAME} source agent for an X-ray run.\n\nArgs:\n    run_id: The run."
    )
    return tool


def _save(store: Store, report: XRayReport, kind: str | None = None, data=None) -> None:
    def write(d: dict) -> None:
        d.setdefault("xray_runs", {})[report.run_id] = report.model_dump()
        d.setdefault("xray_places", {})[report.place_id] = report.run_id

    store.mutate(write)
    if kind:
        payload = data.model_dump() if hasattr(data, "model_dump") else data
        store.publish({"type": "xray", "run_id": report.run_id, "kind": kind, "data": payload})


def _history(claims: list[Claim], evidence: list[Evidence]) -> list[HistoryEntry]:
    """Per field the crawl recorded: the crawl's value, then the advert's now; oldest first."""
    out = []
    now_by_field = {c.field: c for c in claims}
    for e in sorted(
        (e for e in evidence if e.agent == rec.HISTORY_AGENT), key=lambda e: e.fetched_at
    ):
        out.append(
            HistoryEntry(
                field=e.field,
                value=e.value,
                previous_value=None,
                source_name=e.source_name,
                source_url=e.source_url,
                fetched_at=e.fetched_at,
                agent=e.agent,
            )
        )
        if c := now_by_field.get(e.field):
            out.append(
                HistoryEntry(
                    field=c.field,
                    value=c.value,
                    previous_value=e.value,
                    source_name="Advert",
                    source_url=c.source_url,
                    fetched_at=c.captured_at,
                    agent=rec.HISTORY_AGENT,
                )
            )
    return out


def begin(store: Store, ref: str, offline: bool = False, use: str | None = None) -> XRayReport:
    """Load the listing (NotFound if unknown) and save the run as "running"."""
    run_id = f"xr-{uuid.uuid4().hex[:10]}"
    place, listing = load_listing(ref, offline)
    if use:
        place.use = use
    report = XRayReport(
        place_id=place.id,
        listing_id=listing["listing_id"],
        trust_score=None,
        counts=count([]),
        findings=[],
        sources=[],
        run_id=run_id,
        place=PlaceView(**place.model_dump(), title=listing["title"]),
    )
    _save(store, report, "start", {"place": report.place.model_dump()})
    _ctx[run_id] = (place, listing)
    return report


def run_xray(gateway, ref: str, offline: bool = False, report: XRayReport | None = None):
    """One X-ray, synchronously; every step is saved and published as it lands."""
    store = gateway.store
    report = report or begin(store, ref, offline)
    run_id = report.run_id
    place, listing = _ctx[run_id]
    try:
        for module in SOURCES:
            start = time.perf_counter()
            try:
                result = gateway.call(f"source_{module.NAME}", {"run_id": run_id}, run_id)
                claims = [Claim(**c) for c in result["payload"]["claims"]]
                evidence = [Evidence(**e) for e in result["payload"]["evidence"]]
                state = "ok" if claims or evidence else "empty"
                detail = None if evidence or claims else "no record for this address"
            except Exception as e:  # a failed source is shown as unverifiable, never hidden
                claims, evidence, state, detail = [], [], "error", f"{type(e).__name__}: {e}"
            ms = round((time.perf_counter() - start) * 1000)
            status = SourceStatus(
                name=module.NAME, status=state, n_evidence=len(evidence), ms=ms, detail=detail
            )
            report.sources.append(status)
            report.claims += claims
            report.evidence += evidence
            if module.NAME == rec.HISTORY_AGENT and "page" in listing:
                report.place.photos = [
                    Photo(url=u, advert_id=listing["listing_id"]) for u in listing["page"]["photos"]
                ]
            _save(store, report, "source", status)
            for c in claims:
                _save(store, report, "claim", c)
            for e in evidence:
                _save(store, report, "evidence", e)
        report.history = _history(report.claims, report.evidence)
        for h in report.history:
            _save(store, report, "history", h)
        report.findings = rec.reconcile(report.claims, report.evidence, report.sources)
        told = narrate(report.findings, report.claims, report.evidence)
        if told["provider"] == "xai":
            report.grok_calls += told["calls"]
            report.client_calls.grok += told["calls"]
        for f in report.findings:
            _save(store, report, "finding", f)
        report.counts = count(report.findings)
        report.trust_score = trust_score(report.findings)
        _save(
            store,
            report,
            "score",
            {"trust_score": report.trust_score, "counts": report.counts.model_dump()},
        )
        report.status = "done"
    except Exception as e:
        report.status, report.error = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        _ctx.pop(run_id, None)
        _save(store, report, "done", {"status": report.status, "error": report.error})
    return report


def get_report(store: Store, run_id: str) -> dict:
    run = store.snapshot().get("xray_runs", {}).get(run_id)
    if run is None:
        raise NotFound(f"no X-ray run {run_id!r}")
    return run


@router.post("/api/xray", status_code=202)
def start_xray(body: XRayRequest, request: Request) -> dict:
    # shortcut: open route, one thread per run, no rate limit; add a per-IP budget before any
    # paid model or search key is behind it on a public URL.
    ref = body.listing_id or body.url
    if not ref:
        raise ValueError("give listing_id or url")
    gateway = request.app.state.gateway
    report = begin(
        gateway.store, ref, body.offline, body.use
    )  # unknown listing: 404 now, saved run else

    def work():
        try:
            run_xray(gateway, ref, body.offline, report)
        except Exception as e:  # already saved as status "error" by run_xray
            print(json.dumps({"xray_error": report.run_id, "error": str(e)}), flush=True)

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": report.run_id}


@router.get("/api/xray/{run_id}")
def read_xray(run_id: str, store: StoreDep) -> dict:
    return get_report(store, run_id)


@router.get("/api/xray/{run_id}/events")
async def xray_events(run_id: str, request: Request, store: StoreDep) -> StreamingResponse:
    async def stream():
        seq = 0
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not await request.is_disconnected():
            events = await asyncio.to_thread(lambda: store.snapshot().get("events", []))
            for ev in events[seq:]:
                if ev.get("type") == "xray" and ev.get("run_id") == run_id:
                    yield f"event: {ev['kind']}\ndata: {json.dumps(ev['data'])}\n\n"
                    if ev["kind"] == "done":
                        return
            seq = len(events)
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/api/place/{place_id}/graph")
def place_graph(place_id: str, store: StoreDep) -> dict:
    """Nodes and edges: place->has->claim, claim->checked_by->evidence, finding->cites->evidence."""
    run_id = store.snapshot().get("xray_places", {}).get(place_id)
    if run_id is None:
        raise NotFound(f"no X-ray for place {place_id!r}")
    r = get_report(store, run_id)
    nodes = [{"id": place_id, "kind": "place", "data": r["place"]}]
    nodes += [{"id": c["id"], "kind": "claim", "data": c} for c in r["claims"]]
    nodes += [{"id": e["id"], "kind": "evidence", "data": e} for e in r["evidence"]]
    nodes += [{"id": f["id"], "kind": "finding", "data": f} for f in r["findings"]]
    edges = [{"from": place_id, "to": c["id"], "kind": "has"} for c in r["claims"]]
    for f in r["findings"]:
        edges += [{"from": f["id"], "to": e, "kind": "cites"} for e in f["evidence_ids"]]
        if f["claim_id"]:
            edges += [
                {"from": f["claim_id"], "to": e, "kind": "checked_by"} for e in f["evidence_ids"]
            ]
    return {"place_id": place_id, "run_id": run_id, "nodes": nodes, "edges": edges}
