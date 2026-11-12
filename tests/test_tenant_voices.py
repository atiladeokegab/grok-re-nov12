"""tenant_voices: renter quotes come only from a recorded Parallel search, each a verbatim,
grounded, cited info flag; a run never calls Parallel."""

import json

import pytest

from starter.core.errors import SourceOff
from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.verticals.sources import load_listing, tenant_voices
from starter.verticals.xray import run_xray

PAGE = "https://example.org/reviews/macquarie-way"
SAID = "We rented a flat on Macquarie Way for two years and the concierge was brilliant."


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("TENANT_VOICES_DIR", str(tmp_path / "tv"))
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "docs"))
    (tmp_path / "tv").mkdir()

    def write(listing_id: str, results: list[dict]) -> None:
        (tmp_path / "tv" / f"{listing_id}.json").write_text(json.dumps({"results": results}))

    return write


def test_a_recorded_quote_is_a_cited_grounded_info_flag_and_the_score_holds(recorded, tmp_path):
    _, listing = load_listing("demo", offline=True)
    excerpt = f"# Reviews\nGreat transport links. {SAID} See https://x.y/z for more."
    recorded(
        listing["listing_id"],
        [{"url": PAGE, "title": "Macquarie Way reviews", "excerpts": [excerpt]}],
    )
    httpx_post = tenant_voices.httpx.post
    tenant_voices.httpx.post = lambda *a, **k: pytest.fail("a run called Parallel")
    try:
        r = run_xray(build_gateway(Store(tmp_path / "s.json")), "demo", offline=True)
    finally:
        tenant_voices.httpx.post = httpx_post
    [ev] = [e for e in r.evidence if e.field == "tenant_reviews"]
    assert (ev.value, ev.doc_span, ev.source_url) == (SAID, SAID, PAGE)
    assert ev.span and ev.span.quote == SAID and ev.document_id
    [f] = [f for f in r.findings if f.field == "tenant_reviews"]
    assert (f.verdict, f.severity, f.reasoning, f.evidence_ids) == ("flag", "info", SAID, [ev.id])
    assert r.trust_score == 67


def test_no_recording_or_nothing_said_is_off_never_invented(recorded):
    place, listing = load_listing("demo", offline=True)
    with pytest.raises(SourceOff, match="no tenant reviews recorded"):
        tenant_voices.ingest(place, listing)
    recorded(listing["listing_id"], [{"url": PAGE, "title": "t", "excerpts": ["Flats for sale."]}])
    with pytest.raises(SourceOff, match="no tenant reviews found"):
        tenant_voices.ingest(place, listing)


def test_record_makes_one_call_per_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_voices, "RECORDED", tmp_path)
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"search_id": "s1", "usage": [1], "results": [{"url": PAGE, "excerpts": [SAID]}]}

    monkeypatch.setattr(tenant_voices.httpx, "post", lambda *a, **k: calls.append(k) or Resp())
    place, _ = load_listing("demo", offline=True)
    path = tenant_voices.record(place, "x", "key")
    assert "Macquarie Way" in calls[0]["json"]["objective"] and calls[0]["headers"]["x-api-key"]
    assert "usage" not in json.loads(path.read_text())
    with pytest.raises(FileExistsError):
        tenant_voices.record(place, "x", "key")
    assert len(calls) == 1
