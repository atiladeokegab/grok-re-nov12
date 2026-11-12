"""Companies House (api.company-information.service.gov.uk, public register): is the agent or
landlord the advert names a live company? Search by name, take only an exact name match
(case-insensitive, Ltd = Limited), then read its profile and officers. Every response is landed,
and the evidence quotes the profile's own "company_status" line so it grounds verbatim.

Offline, or with no COMPANIES_HOUSE_API_KEY, the source is "off" (SourceOff), never "error".
"""

import json
import os
import re

import httpx2 as httpx

from starter.core.errors import SourceOff
from starter.core.ingest import land
from starter.core.xray import Claim, Evidence, Place

NAME = "companies_house"
SOURCE = "Companies House"
BASE = "https://api.company-information.service.gov.uk"
TIMEOUT = 15
# A company name in the advert's words: capitalised words ending in Ltd / Limited / LLP / PLC.
NAMED = re.compile(r"\b((?:[A-Z][\w&'.-]*\s+){1,6}(?:Ltd|Limited|LLP|PLC))\b\.?")


def norm(name: str) -> str:
    n = re.sub(r"\blimited\b", "ltd", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def _get(listing: dict, key: str, path: str, params: dict | None = None) -> tuple[dict, str]:
    """(json, landed document id) for one API call; the key is the Basic-auth username only."""
    r = httpx.get(BASE + path, params=params, auth=(key, ""), timeout=TIMEOUT)
    r.raise_for_status()
    url = str(r.url)  # the key is never in the URL
    doc = land(listing, raw=r.content, source_url=url, agent=NAME, content_type="application/json")
    return r.json(), doc.id


def named_company(place: Place, listing: dict) -> Claim | None:
    """The agent firm from the crawl row, else a company the advert text names."""
    lid, row = listing["listing_id"], listing.get("crawl") or {}
    base = {"id": f"claim-{lid}-agent_company", "place_id": place.id, "field": "agent_company"}
    if firm := (row.get("agent_firm") or "").strip():
        return Claim(**base, value=firm, source_url=row.get("url"), doc_span=f"agent_firm={firm}")
    page = listing.get("page") or {}
    if m := NAMED.search(page.get("text", "")):
        return Claim(**base, value=m.group(1), source_url=page.get("url"), doc_span=m.group(1))
    return None


def ingest(place: Place, listing: dict) -> tuple[list[Claim], list[Evidence]]:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if listing.get("offline") or not key:
        raise SourceOff("offline" if listing.get("offline") else "no COMPANIES_HOUSE_API_KEY")
    claim = named_company(place, listing)
    if claim is None:
        return [], []
    found, _ = _get(listing, key, "/search/companies", {"q": claim.value})
    hit = next(
        (i for i in found.get("items", []) if norm(i.get("title", "")) == norm(str(claim.value))),
        None,
    )
    if hit is None:  # the reconciler says "no exact Companies House match"
        return [claim], []
    number = hit["company_number"]
    profile, doc_id = _get(listing, key, f"/company/{number}")
    _get(listing, key, f"/company/{number}/officers")
    status = profile.get("company_status", "")
    created = profile.get("date_of_creation", "")
    return [claim], [
        Evidence(
            id=f"ev-{NAME}-{listing['listing_id']}-agent_company",
            place_id=place.id,
            field="agent_company",
            value=status,
            source_name=(
                f"{SOURCE}: {profile.get('company_name', hit['title'])} ({number}), "
                f"incorporated {created}"
            ),
            source_url=f"{BASE}/company/{number}",
            doc_span=f'"company_status": {json.dumps(status, ensure_ascii=False)}',
            document_id=doc_id,
            agent=NAME,
        )
    ]
