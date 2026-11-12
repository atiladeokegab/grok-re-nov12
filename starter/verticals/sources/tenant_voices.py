"""What people who rent there say: renter quotes found by Parallel web search, each cited to the
page it came from. Every quote is a verbatim sentence of a search excerpt; nothing is written or
paraphrased here. Each quote becomes an info flag (context, never scored).

Cost rule: a run never calls Parallel. `record(listing_id)` makes the one live call per listing
(scripts/record_tenant_voices.py) and saves the raw response under fixtures/tenant_voices/; runs
read that file. A listing with no recording, or whose recording found nothing, is "off".
"""

import json
import os
import re
from pathlib import Path

import httpx2 as httpx

from starter.core.errors import SourceOff
from starter.core.ingest import land
from starter.core.xray import Evidence, Place

NAME = "tenant_voices"
FIELD = "tenant_reviews"
URL = "https://api.parallel.ai/v1/search"
RECORDED = Path(__file__).parent / "fixtures" / NAME
MAX_QUOTES = 4
SENTENCE = re.compile(r"[^.!?\n]+[.!?]")
# a renter speaking: first person, and about renting or living there
SPEAKER = re.compile(r"\b(I|I'm|I've|we|we've|my|our)\b", re.I)
TOPIC = re.compile(
    r"\b(rent\w*|landlord|tenan\w*|lease|letting|flat|apartment|building|lived|living|live here|"
    r"neighbou?r\w*|concierge|management|managing agent|noise|noisy|damp|mould|mold|repairs?|"
    r"maintenance|service charge|lift|heating)\b",
    re.I,
)


def query(place: Place) -> dict:
    """The one search request for a place: the street and area, since few buildings have reviews."""
    parts = [p.strip() for p in place.address.split(",")]
    street = re.sub(r"^\d+[a-z]?\s+", "", parts[0], flags=re.I)  # "24 Macquarie Way" -> street
    area = parts[1] if len(parts) > 2 else place.postcode
    return {
        "objective": (
            f"What do tenants who rent homes on {street}, {area} ({place.postcode}) say about "
            "living there: first-hand reviews of the flats, building, landlord or managing agent."
        ),
        "search_queries": [
            f"{street} {area} tenant reviews",
            f"{street} {place.postcode} renting experience",
            f"living on {street} {area} review",
        ],
        "advanced_settings": {"max_results": 8},
    }


def record(place: Place, listing_id: str, key: str) -> Path:
    """The one live Parallel call for a listing; refuses if a recording already exists."""
    path = RECORDED / f"{listing_id}.json"
    if path.exists():
        raise FileExistsError(f"{path} is already recorded: one live call per listing")
    r = httpx.post(URL, json=query(place), headers={"x-api-key": key}, timeout=60)
    r.raise_for_status()
    body = r.json()
    keep = {"query": query(place), "search_id": body.get("search_id"), "results": []}
    for res in body.get("results") or []:  # url, title and excerpts only: no usage, no ids
        keep["results"].append(
            {k: res.get(k) for k in ("url", "title", "publish_date", "excerpts")}
        )
    RECORDED.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, indent=1, ensure_ascii=False) + "\n")
    return path


def quotes(text: str) -> list[str]:
    """Verbatim sentences of an excerpt in which a renter speaks about living there."""
    out = []
    for m in SENTENCE.finditer(text):
        s = m.group(0).strip().lstrip("-*#> ").strip()
        if 40 <= len(s) <= 320 and SPEAKER.search(s) and TOPIC.search(s) and "http" not in s:
            out.append(s)
    return out


def ingest(place: Place, listing: dict) -> tuple[list, list[Evidence]]:
    lid = listing["listing_id"]
    path = Path(os.environ.get("TENANT_VOICES_DIR") or RECORDED) / f"{lid}.json"
    if not path.exists():
        raise SourceOff("no tenant reviews recorded for this listing")
    recorded = json.loads(path.read_text())
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for res in recorded.get("results") or []:
        text = "\n\n".join(res.get("excerpts") or [])
        found = [q for q in quotes(text) if q.lower() not in seen]
        if not found:
            continue
        doc = land(listing, raw=text, source_url=res["url"], agent=NAME, content_type="text/plain")
        for q in found[: MAX_QUOTES - len(evidence)]:
            seen.add(q.lower())
            evidence.append(
                Evidence(
                    id=f"ev-{NAME}-{lid}-{len(evidence) + 1}",
                    place_id=place.id,
                    field=FIELD,
                    value=q,
                    source_name=res.get("title") or res["url"],
                    source_url=res["url"],
                    doc_span=q,
                    agent=NAME,
                    document_id=doc.id,
                )
            )
        if len(evidence) >= MAX_QUOTES:
            break
    if not evidence:
        raise SourceOff("no tenant reviews found")
    return [], evidence
