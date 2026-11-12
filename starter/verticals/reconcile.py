"""The reconciler: claims + evidence -> findings, deterministic. Rules, in order:

1. A claim with evidence for the same field from an independent source (not the advert's own
   history) is `matches` or `disagrees`, citing that evidence.
2. A claim whose value the crawl recorded differently earlier is a `flag` (it changed), citing
   the crawl row. The crawl agreeing is not independent, so it is never a match.
3. A checkable claim nobody could check is `unverifiable`, with the reason from source status.
4. Independent evidence the advert says nothing about (floor area) is an `info` flag.
5. Contextual evidence (photo reuse, reviews, photo history) is a flag at its field's severity;
   it is never turned into a verdict on the claim by inequality.

The reasoning written here is a plain template; a model may rewrite it later, citing only these
evidence ids (narrate), but never changes a verdict.
"""

import re

from starter.core.xray import Claim, Evidence, Finding, SourceStatus

HISTORY_AGENT = "listing_history"
# field -> severity when an independent source disagrees
SEVERITY = {
    "energy_rating": "high",
    "floor_area": "high",
    "property_type": "warn",
    "tenure": "warn",
}
CHECKABLE = set(SEVERITY)  # claims an independent source is expected to check
CHECKED_BY = {"energy_rating": "epc", "floor_area": "epc", "property_type": "epc"}
CONTEXT = {
    "photo_reuse": "warn",
    "photo_history": "warn",
    "tenant_reviews": "info",
    "area_context": "info",
}
UNCLAIMED_INFO = {"floor_area"}
# Companies House statuses that mean the named company cannot be trading normally
COMPANY_DOWN = {
    "dissolved",
    "liquidation",
    "administration",
    "receivership",
    "insolvency-proceedings",
}
AREA_TOLERANCE = 0.10  # an advert's size within 10% of the register's is a match
SQFT_PER_M2 = 10.7639


def _norm(v) -> str:
    s = re.sub(r"[-_]", " ", str(v).lower())
    s = re.sub(r"\b(house|flat|property)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _m2(value, unit) -> float:
    return float(value) / SQFT_PER_M2 if unit in ("sq ft", "sqft") else float(value)


def same(field: str, claim: Claim, ev: Evidence) -> bool:
    if field == "floor_area":
        a, b = _m2(claim.value, claim.unit), _m2(ev.value, ev.unit)
        return abs(a - b) <= AREA_TOLERANCE * b
    if isinstance(claim.value, int | float) and isinstance(ev.value, int | float):
        return abs(float(claim.value) - float(ev.value)) < 0.5
    a, b = _norm(claim.value), _norm(ev.value)
    if not a or not b:  # "House" vs "Flat" both strip to "": compare the words themselves
        a, b = str(claim.value).lower().strip(), str(ev.value).lower().strip()
    return a == b


def _show(v, unit=None) -> str:
    if unit == "GBP" and isinstance(v, int | float):
        return f"£{v:,.0f}"
    return f"{v:g} {unit}" if isinstance(v, float) and unit else str(v)


def reconcile(
    claims: list[Claim], evidence: list[Evidence], sources: list[SourceStatus]
) -> list[Finding]:
    status = {s.name: s for s in sources}
    out: list[Finding] = []

    def add(field, verdict, severity, reasoning, claim=None, evs=()):
        place_id = (claim or evs[0]).place_id
        n = sum(f.field == field for f in out)
        out.append(
            Finding(
                id=f"f-{place_id.removeprefix('place-')}-{field}" + (f"-{n}" if n else ""),
                place_id=place_id,
                field=field,
                verdict=verdict,
                severity=severity,
                claim_id=claim.id if claim else None,
                evidence_ids=[e.id for e in evs],
                reasoning=reasoning,
                model="rules",
            )
        )

    claimed = {c.field for c in claims}
    # observed_at marks a past fact (a snapshot, an old sale): report.history, never a check now
    current = [e for e in evidence if not e.observed_at]
    for c in claims:
        independent = [e for e in current if e.field == c.field and e.agent != HISTORY_AGENT]
        history = [e for e in evidence if e.field == c.field and e.agent == HISTORY_AGENT]
        if c.field == "agent_company":  # evidence is the register's status, not a rival value
            _company(c, independent, add)
            continue
        for e in independent:
            if same(c.field, c, e):
                why = f"Advert says {_show(c.value, c.unit)}; {e.source_name} agrees."
                add(c.field, "matches", "info", why, c, [e])
            else:
                why = (
                    f"Advert says {_show(c.value, c.unit)}; "
                    f"{e.source_name} records {_show(e.value, e.unit)}."
                )
                add(c.field, "disagrees", SEVERITY.get(c.field, "warn"), why, c, [e])
        for e in history:
            if not same(c.field, c, e):
                why = (
                    f"Advert now says {_show(c.value, c.unit)}; the crawl on "
                    f"{e.fetched_at[:10]} recorded {_show(e.value, e.unit)} ({e.doc_span})."
                )
                add(c.field, "flag", "warn", why, c, [e])
        if not independent and c.field in CHECKABLE:
            src = status.get(CHECKED_BY.get(c.field, ""))
            reason = (
                f"{src.name} returned {src.status}" + (f": {src.detail}" if src.detail else "")
                if src
                else "no source checks this field yet"
            )
            add(c.field, "unverifiable", "info", f"Could not check: {reason}.", c)

    for e in current:
        if e.agent == HISTORY_AGENT:
            continue
        if e.field in UNCLAIMED_INFO and e.field not in claimed:
            what = e.field.replace("_", " ")
            why = f"The advert states no {what}; {e.source_name} records {_show(e.value, e.unit)}."
            add(e.field, "flag", "info", why, evs=[e])
        elif e.field in CONTEXT:
            add(e.field, "flag", CONTEXT[e.field], e.doc_span or f"{e.source_name}.", evs=[e])

    for s in sources:  # a source that said nothing is shown, never silently dropped
        if s.status not in ("ok", "off") and not any(
            CHECKED_BY.get(f.field) == s.name for f in out
        ):
            detail = f": {s.detail}" if s.detail else ""
            out.append(
                Finding(
                    id=f"f-source-{s.name}",
                    place_id=claims[0].place_id if claims else "",
                    field=s.name,
                    verdict="unverifiable",
                    severity="info",
                    reasoning=f"{s.name} returned {s.status}{detail}.",
                    model="rules",
                )
            )
    return out


def _company(c: Claim, evs: list[Evidence], add) -> None:
    """Rule 1 for the named agent: an active company matches; a closed or insolvent one
    disagrees (high); any other status is a warn flag; no exact register match is unverifiable."""
    if not evs:
        why = f"Could not check: no exact Companies House match for {c.value}."
        add(c.field, "unverifiable", "info", why, c)
    for e in evs:
        said = f"Advert names {c.value}; {e.source_name} lists it as {e.value}."
        if e.value == "active":
            add(c.field, "matches", "info", said, c, [e])
        elif e.value in COMPANY_DOWN:
            add(c.field, "disagrees", "high", said, c, [e])
        else:
            add(c.field, "flag", "warn", said, c, [e])
