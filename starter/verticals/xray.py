"""X-ray: one listing in, a Trust Score and sourced findings out.

POST /api/xray {listing_id | url} starts a run in a thread and returns {run_id};
GET /api/xray/{run_id} is the XRayReport; GET /api/xray/{run_id}/events streams it (SSE) as it
grows: `source`, `claim`, `evidence`, `finding`, `history`, `score`, then `done` (terminal; also
sent on error, with status "error"). Each event's data is the full object.
GET /api/place/{id}/graph is the evidence graph of the latest run for that place.
Ingestion (contract: ingest-contract v1): each source's raw originals are landed as Documents,
every evidence quote is grounded in its document (`ingestion.landed`, `ingestion.parsed`,
`ingestion.extracted`, `ingestion.linked`); GET /api/document/{id}[/raw] and
GET /api/finding/{id}/trace walk place -> document -> evidence -> finding.

Each source agent runs as a read-only gateway tool `source_<name>`, so every call is audited.
"""

import asyncio
import json
import threading
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from starter.core.errors import NotFound
from starter.core.ingest import decoded_text, ground, land, raw_bytes
from starter.core.store import Store
from starter.core.xray import (
    Claim,
    Document,
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
from starter.verticals import cursor_step
from starter.verticals import reconcile as rec
from starter.verticals.narrate import narrate
from starter.verticals.sources import SOURCES, load_listing
from starter.verticals.sources import epc as epc_source

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


def _land_known(name: str, listing: dict) -> None:
    """Land what existing sources fetched without calling land() themselves."""
    if name == "listing_history" and (page := listing.get("page")):
        land(
            listing,
            raw=page["text"],  # shortcut: the advert's visible text, not its HTML; the source
            source_url=page["url"],  # keeps no HTML. Land the HTML inside listing_history.
            agent=name,
            content_type="text/plain",
            fetched_at=page.get("fetched_at"),
        )
    if name == "epc" and listing.get("offline") and listing.get("fixture"):
        fx = listing["fixture"].get("epc", {})
        for path, text in fx.get("certificates", {}).items():
            land(
                listing,
                raw=text,
                source_url=epc_source.BASE + path,
                agent=name,
                content_type="text/plain",
                fetched_at=fx.get("fetched_at"),
            )
    # shortcut: live EPC certificates are fetched inside epc._search and never reach here;
    # epc.py needs one land() call there (Atlas owns it).


def _ground(store: Store, report: XRayReport, evidence: list[Evidence]) -> None:
    """Link each evidence to its document (by id, else by url) and ground its quote there."""
    docs = report.documents
    by_id = {d.id: d for d in docs}
    texts: dict[str, str | None] = {}
    tally: dict[str, list[int]] = {}  # document_id -> [n_spans, n_dropped]

    def text(doc: Document) -> str:
        if doc.id not in texts:
            texts[doc.id] = decoded_text(doc)
        return texts[doc.id] or ""

    for e in evidence:
        if e.document_id is None and e.source_url:
            # A url match alone is a guess (the crawl row cites the advert's url but is not its
            # text), so an inferred link is kept only when the quote is found in that document.
            for d in reversed(docs):
                if d.url == e.source_url and (span := ground(text(d), e.doc_span or "")):
                    e.document_id, e.span = d.id, span
                    break
        doc = by_id.get(e.document_id or "")
        if doc is None:
            continue
        if e.span is None and e.doc_span:
            e.span = ground(text(doc), e.doc_span)  # None: the quote is dropped
        if e.doc_span:
            t = tally.setdefault(doc.id, [0, 0])
            t[0 if e.span else 1] += 1
        _save(store, report, "ingestion.extracted", {"evidence_id": e.id, "document_id": doc.id})
    for doc_id, (n_spans, n_dropped) in tally.items():
        data = {"document_id": doc_id, "n_spans": n_spans, "n_dropped": n_dropped}
        _save(store, report, "ingestion.parsed", data)


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "bytes_path"}


def _history(claims: list[Claim], evidence: list[Evidence]) -> list[HistoryEntry]:
    """Per field the crawl recorded: the crawl's value, then the advert's now; plus every
    evidence with observed_at (when the fact was true). Oldest first."""
    out = []
    now_by_field = {c.field: c for c in claims}
    for e in sorted(
        (e for e in evidence if e.agent == rec.HISTORY_AGENT),
        key=lambda e: e.observed_at or e.fetched_at,
    ):
        out.append(
            HistoryEntry(
                field=e.field,
                value=e.value,
                previous_value=None,
                source_name=e.source_name,
                source_url=e.source_url,
                fetched_at=e.observed_at or e.fetched_at,
                agent=e.agent,
                document_id=e.document_id,
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
    last: dict[str, object] = {}
    for e in sorted(
        (e for e in evidence if e.observed_at and e.agent != rec.HISTORY_AGENT),
        key=lambda e: e.observed_at,
    ):
        out.append(
            HistoryEntry(
                field=e.field,
                value=e.value if not isinstance(e.value, dict | list) else str(e.value),
                previous_value=last.get(e.field),
                source_name=e.source_name,
                source_url=e.source_url,
                fetched_at=e.observed_at,
                agent=e.agent,
                document_id=e.document_id,
            )
        )
        last[e.field] = out[-1].value
    return sorted(out, key=lambda h: h.fetched_at)  # stable: a crawl pair keeps its order


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
            _land_known(module.NAME, listing)
            landed = listing.get("_documents", [])[len(report.documents) :]
            report.documents += landed
            for d in landed:
                _save(store, report, "ingestion.landed", {"document": _public(d.model_dump())})
            _ground(store, report, evidence)
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
        doc_of = {e.id: e.document_id for e in report.evidence}
        for f in report.findings:
            _save(store, report, "finding", f)
            ids = list(dict.fromkeys(d for i in f.evidence_ids if (d := doc_of.get(i))))
            _save(store, report, "ingestion.linked", {"finding_id": f.id, "document_ids": ids})
        report.counts = count(report.findings)
        report.trust_score = trust_score(report.findings)
        _save(
            store,
            report,
            "score",
            {"trust_score": report.trust_score, "counts": report.counts.model_dump()},
        )
        if (summary := cursor_step.summarize(report.model_dump())) is not None:
            report.client_calls.cursor_sdk += 1
            _save(store, report, "cursor_summary", summary)
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
    run = get_report(store, run_id)
    return {**run, "documents": [_public(d) for d in run.get("documents", [])]}


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
    """Nodes and edges: place->has->claim, claim->checked_by->evidence, finding->cites->evidence,
    place->landed->document, document->contains->evidence."""
    # shortcut: with STORE=surreal the graph is still computed from the saved report, not from
    # RELATE edges; write place->document->evidence->finding relations when a query needs them.
    run_id = store.snapshot().get("xray_places", {}).get(place_id)
    if run_id is None:
        raise NotFound(f"no X-ray for place {place_id!r}")
    r = get_report(store, run_id)
    nodes = [{"id": place_id, "kind": "place", "data": r["place"]}]
    nodes += [{"id": c["id"], "kind": "claim", "data": c} for c in r["claims"]]
    nodes += [{"id": e["id"], "kind": "evidence", "data": e} for e in r["evidence"]]
    nodes += [{"id": f["id"], "kind": "finding", "data": f} for f in r["findings"]]
    docs = r.get("documents", [])
    nodes += [{"id": d["id"], "kind": "document", "data": _public(d)} for d in docs]
    edges = [{"from": place_id, "to": c["id"], "kind": "has"} for c in r["claims"]]
    edges += [{"from": place_id, "to": d["id"], "kind": "landed"} for d in docs]
    edges += [
        {"from": e["document_id"], "to": e["id"], "kind": "contains"}
        for e in r["evidence"]
        if e.get("document_id")
    ]
    for f in r["findings"]:
        edges += [{"from": f["id"], "to": e, "kind": "cites"} for e in f["evidence_ids"]]
        if f["claim_id"]:
            edges += [
                {"from": f["claim_id"], "to": e, "kind": "checked_by"} for e in f["evidence_ids"]
            ]
    return {"place_id": place_id, "run_id": run_id, "nodes": nodes, "edges": edges}


def _find_document(store: Store, doc_id: str) -> dict:
    for run in reversed(store.snapshot().get("xray_runs", {}).values()):
        for d in run.get("documents", []):
            if d["id"] == doc_id:
                return d
    raise NotFound(f"no document {doc_id!r}")


@router.get("/api/document/{doc_id}")
def read_document(doc_id: str, store: StoreDep) -> dict:
    doc = _find_document(store, doc_id)
    return {
        "document": _public(doc),
        "text": decoded_text(doc),
        "raw_url": f"/api/document/{doc_id}/raw",
    }


@router.get("/api/document/{doc_id}/raw")
def read_document_raw(doc_id: str, store: StoreDep) -> Response:
    doc = _find_document(store, doc_id)
    try:
        data = raw_bytes(doc)
    except FileNotFoundError:
        raise NotFound(f"document {doc_id!r} is not on this instance") from None
    return Response(data, media_type=doc["content_type"])


@router.get("/api/finding/{finding_id}/trace")
def finding_trace(finding_id: str, store: StoreDep, run_id: str | None = None) -> dict:
    runs = store.snapshot().get("xray_runs", {})
    candidates = [runs[run_id]] if run_id in runs else [] if run_id else reversed(runs.values())
    for run in candidates:
        finding = next((f for f in run["findings"] if f["id"] == finding_id), None)
        if finding:
            break
    else:
        raise NotFound(f"no finding {finding_id!r}" + (f" in run {run_id!r}" if run_id else ""))
    docs = {d["id"]: d for d in run.get("documents", [])}
    evidence = {e["id"]: e for e in run["evidence"]}
    texts: dict[str, str | None] = {}
    steps, chain_docs = [], []
    for eid in finding["evidence_ids"]:
        e = evidence.get(eid)
        if e is None:
            continue
        doc, verified = docs.get(e.get("document_id") or ""), False
        if doc:
            chain_docs.append(doc["id"])
            if (span := e.get("span")) is not None:
                if doc["id"] not in texts:
                    texts[doc["id"]] = decoded_text(doc)
                verified = (texts[doc["id"]] or "")[span["start"] : span["end"]] == span["quote"]
        steps.append(
            {"evidence": e, "document": _public(doc) if doc else None, "quote_verified": verified}
        )
    claim = next((c for c in run["claims"] if c["id"] == finding["claim_id"]), None)
    chain = [{"kind": "place", "id": run["place_id"]}]
    chain += [{"kind": "document", "id": d} for d in dict.fromkeys(chain_docs)]
    chain += [{"kind": "evidence", "id": s["evidence"]["id"]} for s in steps]
    chain += [{"kind": "finding", "id": finding_id}]
    return {
        "run_id": run["run_id"],
        "place": run["place"],
        "finding": finding,
        "claim": claim,
        "steps": steps,
        "chain": chain,
    }
