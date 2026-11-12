"""X-ray: one listing in, a Trust Score and sourced findings out.

POST /api/xray {listing_id | url} starts a run in a thread and returns {run_id};
GET /api/xray/{run_id} is the XRayReport; GET /api/xray/{run_id}/events streams it (SSE) as it
grows: `source`, `claim`, `evidence`, `finding`, `history`, `score`, then `done` (terminal; also
sent on error, with status "error"). Each event's data is the full object.
GET /api/gallery lists the 'try these' offline listings.
GET /api/place/{id}/graph is the evidence graph of the latest run for that place.
Ingestion (contract: ingest-contract v1): each source's raw originals are landed as Documents,
every evidence quote is grounded in its document (`ingestion.landed`, `ingestion.parsed`,
`ingestion.extracted`, `ingestion.linked`); GET /api/document/{id}[/raw] and
GET /api/finding/{id}/trace walk place -> document -> evidence -> finding.

Each source agent runs as a read-only gateway tool `source_<name>`, so every call is audited.
"""

import asyncio
import json
import mimetypes
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from starter.core.errors import NotFound, SourceOff
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
from starter.verticals import cursor_step, xray_limit
from starter.verticals import reconcile as rec
from starter.verticals.narrate import narrate
from starter.verticals.sources import FIXTURES, SOURCES, load_listing
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


_buffers: dict[str, list[dict]] = {}  # run_id -> events held until the next _flush


def _save(store: Store, report: XRayReport, kind: str | None = None, data=None) -> None:
    """Save the report and publish one event. Inside run_xray events are held and written in one
    store write per step (_flush): on GCS every write rewrites the whole object (~1/s)."""
    events = []
    if kind:
        payload = data.model_dump() if hasattr(data, "model_dump") else data
        events.append({"type": "xray", "run_id": report.run_id, "kind": kind, "data": payload})
    if (held := _buffers.get(report.run_id)) is not None:
        held += events
        return
    _write(store, report, events)


def _flush(store: Store, report: XRayReport) -> None:
    _write(store, report, _buffers.get(report.run_id, []))
    _buffers[report.run_id] = []


def _write(store: Store, report: XRayReport, events: list[dict]) -> None:
    def write(d: dict) -> None:
        d.setdefault("xray_runs", {})[report.run_id] = report.model_dump()
        d.setdefault("xray_places", {})[report.place_id] = report.run_id
        log = d.setdefault("events", [])
        for e in events:  # the same shape Store.publish stores
            log.append({"seq": len(log) + 1, "ts": time.time(), **e})

    store.mutate(write)


def _land_known(name: str, listing: dict) -> None:
    """Land what existing sources fetched without calling land() themselves."""
    if name == "listing_history" and (row := listing.get("crawl")):
        land(  # key=value lines, so the crawl evidence's "price_gbp=770000.0" grounds verbatim
            listing,
            raw="\n".join(f"{k}={v}" for k, v in row.items()),
            source_url=row["url"] + "#crawl",
            agent=name,
            content_type="text/plain",
            fetched_at=row.get("crawled_at") or None,
        )
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


def _ground_in(text: str, doc: Document, quote: str):
    if (span := ground(text, quote)) or not doc.url.endswith("#crawl"):
        return span
    # crawl quotes read "price_gbp=770000.0 (guide/asking)": the key=value is the row's words
    return ground(text, quote.split(" ", 1)[0])


def _ground(
    store: Store, report: XRayReport, evidence: list[Evidence], claims: list[Claim] = ()
) -> None:
    """Link each evidence and claim to its document (by id, else by url) and ground its quote."""
    docs = report.documents
    by_id = {d.id: d for d in docs}
    texts: dict[str, str | None] = {}
    tally: dict[str, list[int]] = {}  # document_id -> [n_spans, n_dropped]

    def text(doc: Document) -> str:
        if doc.id not in texts:
            texts[doc.id] = decoded_text(doc)
        return texts[doc.id] or ""

    for e in [*claims, *evidence]:
        if e.document_id is None and e.source_url:
            # A url match alone is a guess (the crawl row cites the advert's url but is not its
            # text), so an inferred link is kept only when the quote is found in that document.
            for d in reversed(docs):
                if d.url in (e.source_url, e.source_url + "#crawl") and (
                    span := _ground_in(text(d), d, e.doc_span or "")
                ):
                    e.document_id, e.span = d.id, span
                    break
        doc = by_id.get(e.document_id or "")
        if doc is None:
            continue
        if e.span is None and e.doc_span:
            e.span = _ground_in(text(doc), doc, e.doc_span)  # None: the quote is dropped
        if e.doc_span:
            t = tally.setdefault(doc.id, [0, 0])
            t[0 if e.span else 1] += 1
        if isinstance(e, Evidence):
            data = {"evidence_id": e.id, "document_id": doc.id}
            _save(store, report, "ingestion.extracted", data)
    for doc_id, (n_spans, n_dropped) in tally.items():
        data = {"document_id": doc_id, "n_spans": n_spans, "n_dropped": n_dropped}
        _save(store, report, "ingestion.parsed", data)


def _warn(step: str, source: str, e: Exception) -> None:
    print(json.dumps({"ingest_warning": step, "source": source, "error": repr(e)}), flush=True)


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
                fetched_at=e.fetched_at,
                agent=e.agent,
                document_id=e.document_id,
                observed_at=e.observed_at,
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
                    document_id=c.document_id,
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
                fetched_at=e.fetched_at,
                agent=e.agent,
                document_id=e.document_id,
                observed_at=e.observed_at,
            )
        )
        last[e.field] = out[-1].value
    # stable: a crawl pair keeps its order
    return sorted(out, key=lambda h: h.observed_at or h.fetched_at)


_emitted: dict[str, dict[str, str]] = {}  # run_id -> what each finding / the score last said


def _score(store: Store, report: XRayReport, findings=None) -> None:
    """Replace the findings wholesale (an id may flip between steps) and publish only what
    changed. No score event while the score is still null (nothing checkable yet). Without
    `findings`, the deterministic rules on what has arrived so far."""
    if findings is None:
        findings = rec.reconcile(report.claims, report.evidence, report.sources)
    report.findings = findings
    report.counts = count(findings)
    report.trust_score = trust_score(findings)
    seen = _emitted.setdefault(report.run_id, {})
    for f in findings:
        if seen.get(f.id) != (now := f.model_dump_json()):
            seen[f.id] = now
            _save(store, report, "finding", f)
    data = {"trust_score": report.trust_score, "counts": report.counts.model_dump()}
    if report.trust_score is not None and seen.get("score") != (now := json.dumps(data)):
        seen["score"] = now
        _save(store, report, "score", data)


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


def _fetch(gateway, module, run_id: str):
    start = time.perf_counter()
    try:
        result = gateway.call(f"source_{module.NAME}", {"run_id": run_id}, run_id)
        claims = [Claim(**c) for c in result["payload"]["claims"]]
        evidence = [Evidence(**e) for e in result["payload"]["evidence"]]
        state = "ok" if claims or evidence else "empty"
        detail = None if evidence or claims else "no record for this address"
    except SourceOff as e:  # switched off (offline or no key): not a failure
        claims, evidence, state, detail = [], [], "off", str(e)
    except Exception as e:  # a failed source is shown as unverifiable, never hidden
        claims, evidence, state, detail = [], [], "error", f"{type(e).__name__}: {e}"
    return claims, evidence, state, detail, round((time.perf_counter() - start) * 1000)


BUDGET_S = 10.0  # a whole run's sources; one still running then is reported, not waited for


def _fetch_all(gateway, run_id: str):
    """Yield (module, outcome) as each source finishes. The advert's own page goes first (later
    sources read listing["page"]); the rest run in parallel so wall time is the slowest one.
    Past BUDGET_S every unfinished source yields status "error", "timed out"."""
    budget, start = BUDGET_S, time.monotonic()
    first = [m for m in SOURCES if m.NAME == rec.HISTORY_AGENT]
    pool = ThreadPoolExecutor(max_workers=len(SOURCES))
    try:
        for group in (first, [m for m in SOURCES if m not in first]):
            futures = {pool.submit(_fetch, gateway, m, run_id): m for m in group}
            try:
                left = max(0.0, start + budget - time.monotonic())
                for fut in as_completed(futures, timeout=left):
                    yield futures.pop(fut), fut.result()
            except TimeoutError:
                ms = round((time.monotonic() - start) * 1000)
                for m in futures.values():
                    yield m, ([], [], "error", f"timed out after {budget:g} s", ms)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a straggler finishes unobserved


def _unreadable(report: XRayReport, place) -> str | None:
    """Couldn't read this listing: why, and what was read anyway. None when the advert read."""
    if report.claims:
        return None
    page = next((s for s in report.sources if s.name == rec.HISTORY_AGENT), None)
    if page is None or page.status in ("ok", "empty"):
        why = "no price, bedrooms, floor area, tenure or energy rating found in it"
    else:
        why = page.detail or page.status
    read = sorted({e.field for e in report.evidence}) + (["postcode"] if place.postcode else [])
    return f"Couldn't read this listing: {why}. Read anyway: {', '.join(read) or 'nothing'}."


NO_NARRATION = {"provider": None, "model": "rules", "calls": 0, "error": None}


def run_xray(gateway, ref: str, offline: bool = False, report: XRayReport | None = None):
    """One X-ray, synchronously; every step is saved and published as it lands."""
    store = gateway.store
    report = report or begin(store, ref, offline)
    run_id = report.run_id
    place, listing = _ctx[run_id]
    _buffers[run_id] = []
    try:
        batches = {}
        for module, (claims, evidence, state, detail, ms) in _fetch_all(gateway, run_id):
            batches[module.NAME] = (claims, evidence)
            try:  # provenance is extra: a landing or grounding failure never fails the run
                _land_known(module.NAME, listing)
            except Exception as e:
                _warn("land", module.NAME, e)
            landed = listing.get("_documents", [])[len(report.documents) :]
            report.documents += landed
            for d in landed:
                _save(store, report, "ingestion.landed", {"document": _public(d.model_dump())})
            try:
                _ground(store, report, evidence, claims)
            except Exception as e:
                _warn("ground", module.NAME, e)
            status = SourceStatus(
                name=module.NAME, status=state, n_evidence=len(evidence), ms=ms, detail=detail
            )
            report.sources.append(status)
            report.claims += claims
            report.evidence += evidence
            if module.NAME == rec.HISTORY_AGENT and listing.get("page"):
                report.place.photos = [
                    Photo(url=u, advert_id=listing["listing_id"]) for u in listing["page"]["photos"]
                ]
            _save(store, report, "source", status)
            for c in claims:
                _save(store, report, "claim", c)
            for e in evidence:
                _save(store, report, "evidence", e)
            _score(store, report)  # a provisional score after every source, status "running"
            _flush(store, report)  # one store write per source
        # sources finish in any order: put them back in SOURCES order so finding ids are stable
        rank = {m.NAME: i for i, m in enumerate(SOURCES)}
        report.sources.sort(key=lambda s: rank[s.name])
        report.claims = [c for m in SOURCES for c in batches.get(m.NAME, ((), ()))[0]]
        report.evidence = [e for m in SOURCES for e in batches.get(m.NAME, ((), ()))[1]]
        report.history = _history(report.claims, report.evidence)
        for h in report.history:
            _save(store, report, "history", h)
        findings = rec.reconcile(report.claims, report.evidence, report.sources)
        _score(store, report, findings)
        _flush(store, report)  # the final score lands now; the model calls below only reword
        with ThreadPoolExecutor(max_workers=1) as pool:  # Cursor summary and narration overlap
            # offline (fixtures, smoke, demo replays) never spends a paid model call
            summarizing = pool.submit(
                lambda: None if offline else cursor_step.summarize(report.model_dump())
            )
            told = NO_NARRATION if offline else narrate(findings, report.claims, report.evidence)
            if told["provider"] == "xai":
                report.grok_calls += told["calls"]
                report.client_calls.grok += told["calls"]
            _score(store, report, findings)  # publishes only the reworded findings
            doc_of = {e.id: e.document_id for e in report.evidence}
            for f in report.findings:
                ids = list(dict.fromkeys(d for i in f.evidence_ids if (d := doc_of.get(i))))
                _save(store, report, "ingestion.linked", {"finding_id": f.id, "document_ids": ids})
            summary = summarizing.result()
        if summary is not None:
            report.client_calls.cursor_sdk += 1
            _save(store, report, "cursor_summary", summary)
        report.status = "done"
    except Exception as e:  # saved as status "error", returned: a paste never crashes a caller
        report.status, report.error = "error", f"{type(e).__name__}: {e}"
        _warn("run", run_id, e)
    finally:
        _ctx.pop(run_id, None)
        report.message = _unreadable(report, place)
        data = {"status": report.status, "message": report.message, "error": report.error}
        _save(store, report, "done", data)
        _flush(store, report)
        _buffers.pop(run_id, None)
        _emitted.pop(run_id, None)
    return report


def get_report(store: Store, run_id: str) -> dict:
    run = store.snapshot().get("xray_runs", {}).get(run_id)
    if run is None:
        raise NotFound(f"no X-ray run {run_id!r}")
    return run


@router.get("/api/gallery")
def gallery() -> list[dict]:
    """'Try these': real crawl listings recorded offline, one per discrepancy type. Start one with
    POST /api/xray {"listing_id": name, "offline": true}."""
    out = []
    for p in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(p.read_text())
        if g := fx.get("gallery"):
            out.append({**g, "listing_id": fx["listing_id"], "url": fx["crawl"]["url"]})
    return out


@router.post("/api/xray", status_code=202)
def start_xray(body: XRayRequest, request: Request) -> dict:
    ref = body.listing_id or body.url
    if not ref:
        raise ValueError("give listing_id or url")
    gateway = request.app.state.gateway
    if cached := xray_limit.cached_demo(gateway.store, body):  # a demo repeat: no new run
        return {"run_id": cached}
    xray_limit.check(request)  # 429 over the per-IP or global budget
    report = begin(
        gateway.store, ref, body.offline, body.use
    )  # unknown listing: 404 now, saved run else
    xray_limit.remember_demo(body, report.run_id)

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
        for e in [*r["claims"], *r["evidence"]]
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
        raise NotFound(f"document {doc_id!r} is no longer stored") from None
    # untrusted source bytes from our own origin: download only, never rendered or sniffed (XSS)
    ext = mimetypes.guess_extension(doc["content_type"].split(";")[0].strip()) or ".bin"
    headers = {
        "Content-Disposition": f'attachment; filename="{doc_id}{ext}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    return Response(data, media_type=doc["content_type"], headers=headers)


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

    def check(item: dict) -> tuple[dict | None, bool]:
        """(its document, whether text[span.start:span.end] == span.quote)."""
        doc = docs.get(item.get("document_id") or "")
        if doc is None or (span := item.get("span")) is None:
            return doc, False
        if doc["id"] not in texts:
            texts[doc["id"]] = decoded_text(doc)
        return doc, (texts[doc["id"]] or "")[span["start"] : span["end"]] == span["quote"]

    steps, chain_docs = [], []
    for eid in finding["evidence_ids"]:
        if (e := evidence.get(eid)) is None:
            continue
        doc, verified = check(e)
        if doc:
            chain_docs.append(doc["id"])
        steps.append(
            {"evidence": e, "document": _public(doc) if doc else None, "quote_verified": verified}
        )
    claim = next((c for c in run["claims"] if c["id"] == finding["claim_id"]), None)
    claim_doc, claim_verified = check(claim) if claim else (None, False)
    # place -> document(advert) -> claim -> finding <- evidence <- document(source), flattened
    chain = [{"kind": "place", "id": run["place_id"]}]
    if claim_doc:
        chain.append({"kind": "document", "id": claim_doc["id"]})
    if claim:
        chain.append({"kind": "claim", "id": claim["id"]})
    chain += [{"kind": "document", "id": d} for d in dict.fromkeys(chain_docs)]
    chain += [{"kind": "evidence", "id": s["evidence"]["id"]} for s in steps]
    chain += [{"kind": "finding", "id": finding_id}]
    return {
        "run_id": run["run_id"],
        "place": run["place"],
        "finding": finding,
        "claim": claim,
        "claim_document": _public(claim_doc) if claim_doc else None,
        "claim_quote_verified": claim_verified,
        "steps": steps,
        "chain": chain,
    }
