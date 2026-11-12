"""The X-ray contract (day-spec 'Contract', amended 19:16Z).
Owned by Zeus: change by change-request.

A source agent is a module in starter/verticals/sources/ with NAME and
`ingest(place, listing) -> (list[Claim], list[Evidence])`. The reconciler turns claims and
evidence into findings; the score is computed here so the page, the API and MCP agree on it.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["matches", "disagrees", "unverifiable", "flag"]
Severity = Literal["info", "warn", "high"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Place(BaseModel):
    id: str
    address: str
    postcode: str
    uprn: str | None = None
    lat: float | None = None
    lng: float | None = None
    building_id: str | None = None
    use: Literal["residential", "office"] = "residential"


class Photo(BaseModel):
    url: str
    advert_id: str
    phash: str | None = None


class PlaceView(Place):
    """Place as the page shows it (amendment 19:16Z)."""

    title: str = ""
    photos: list[Photo] = []


class Claim(BaseModel):
    id: str
    place_id: str
    field: str
    value: str | float | int | None
    unit: str | None = None
    source: Literal["listing", "application", "rent_roll"] = "listing"
    source_url: str | None = None  # the advert the claim was read from
    doc_span: str | None = None  # the exact words the value was read from
    captured_at: str = Field(default_factory=now)


class Evidence(BaseModel):
    id: str
    place_id: str
    field: str
    value: str | float | int | dict | list | None
    unit: str | None = None
    source_name: str
    source_url: str | None = None
    doc_span: str | None = None
    fetched_at: str = Field(default_factory=now)
    agent: str  # the source module that fetched it


class Finding(BaseModel):
    id: str
    place_id: str
    field: str
    verdict: Verdict
    severity: Severity = "info"
    claim_id: str | None = None
    evidence_ids: list[str] = []
    reasoning: str
    model: str  # "rules", "fake" or the Grok model id that wrote the reasoning
    created_at: str = Field(default_factory=now)


class SourceStatus(BaseModel):
    name: str
    status: Literal["ok", "empty", "error"]
    n_evidence: int = 0
    ms: int = 0
    detail: str | None = None  # why empty or error; shown on unverifiable findings


class HistoryEntry(BaseModel):
    field: str
    value: str | float | int | None
    previous_value: str | float | int | None
    source_name: str
    source_url: str | None = None
    fetched_at: str
    agent: str
    advert_id: str | None = None


class Counts(BaseModel):
    matches: int = 0
    disagrees: int = 0
    unverifiable: int = 0
    flag: int = 0


class XRay(BaseModel):
    place_id: str
    listing_id: str
    trust_score: int | None  # None while nothing could be checked; never a made-up 100
    counts: Counts
    findings: list[Finding]
    sources: list[SourceStatus]
    grok_calls: int = 0
    run_id: str


class McpCalls(BaseModel):
    grok_bot: int = 0
    cursor: int = 0
    other: int = 0


class ClientCalls(BaseModel):
    grok: int = 0
    cursor_sdk: int = 0
    mcp: McpCalls = McpCalls()


class XRayReport(XRay):
    """GET /api/xray/{run_id}: the XRay plus everything the page draws (amendment 19:16Z)."""

    status: Literal["running", "done", "error"] = "running"
    error: str | None = None
    place: PlaceView
    claims: list[Claim] = []
    evidence: list[Evidence] = []
    history: list[HistoryEntry] = []  # oldest first
    client_calls: ClientCalls = ClientCalls()


# A disagreement costs its severity's weight; a flag costs half of it. Info costs nothing.
WEIGHTS: dict[str, float] = {"info": 0.0, "warn": 0.5, "high": 1.0}
FLAG_FACTOR = 0.5


def count(findings: list[Finding]) -> Counts:
    c = Counts()
    for f in findings:
        setattr(c, f.verdict, getattr(c, f.verdict) + 1)
    return c


def trust_score(findings: list[Finding]) -> int | None:
    """round(100 * matches / (matches + weighted disagreements)); unverifiable is excluded and
    reported separately in counts."""
    matches = sum(f.verdict == "matches" for f in findings)
    against = sum(
        WEIGHTS[f.severity] * (FLAG_FACTOR if f.verdict == "flag" else 1)
        for f in findings
        if f.verdict in ("disagrees", "flag")
    )
    if matches + against == 0:
        return None
    return round(100 * matches / (matches + against))
