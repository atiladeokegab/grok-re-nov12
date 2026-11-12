import json
from pathlib import Path

import pytest

from starter.core.errors import SourceOff
from starter.core.ingest import decoded_text, ground
from starter.core.store import Store
from starter.core.xray import Place, SourceStatus
from starter.runtime.factory import build_gateway
from starter.verticals.reconcile import reconcile
from starter.verticals.sources import companies_house as ch
from starter.verticals.xray import run_xray

FX = Path(__file__).parent / "fixtures/companies_house"
PLACE = Place(id="place-x", address="1 Test Road", postcode="ZZ99 9ZZ")
OK = [SourceStatus(name="companies_house", status="ok")]


class Resp:
    def __init__(self, url: str, body: bytes):
        self.url, self.content = url, body

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


@pytest.fixture
def api(monkeypatch, tmp_path):
    """The API from fixtures; returns the list of calls made."""
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "docs"))
    calls, profile = [], {"name": "profile_active.json"}

    def get(url, params=None, auth=None, timeout=None):
        calls.append((url, params, auth))
        name = (
            "search.json"
            if url.endswith("/search/companies")
            else "officers.json"
            if url.endswith("/officers")
            else profile["name"]
        )
        return Resp(url, (FX / name).read_bytes())

    monkeypatch.setattr(ch.httpx, "get", get)
    return calls, profile


def _listing(firm="Example Lettings Limited"):
    return {
        "listing_id": "x",
        "offline": False,
        "crawl": {"url": "https://example.test/ad/1", "agent_firm": firm},
    }


def test_an_active_company_matches_and_its_quote_grounds_in_the_landed_json(api):
    calls, _ = api
    listing = _listing()
    claims, evidence = ch.ingest(PLACE, listing)
    assert [c.value for c in claims] == ["Example Lettings Limited"]
    [ev] = evidence
    assert ev.value == "active" and "00000001" in ev.source_name
    assert all(auth == ("test-key", "") and "test-key" not in url for url, _, auth in calls)
    [doc] = [d for d in listing["_documents"] if d.id == ev.document_id]
    assert doc.content_type == "application/json"
    assert ground(decoded_text(doc), ev.doc_span) is not None  # quote_verified
    assert len(listing["_documents"]) == 3  # search, profile and officers all landed
    [f] = reconcile(claims, evidence, OK)
    assert (f.verdict, f.severity) == ("matches", "info")


def test_a_dissolved_company_disagrees_high(api):
    api[1]["name"] = "profile_dissolved.json"
    claims, evidence = ch.ingest(PLACE, _listing())
    [f] = reconcile(claims, evidence, OK)
    assert (f.verdict, f.severity) == ("disagrees", "high")
    assert "dissolved" in f.reasoning and "fraud" not in f.reasoning.lower()


def test_no_exact_name_match_is_unverifiable(api):
    claims, evidence = ch.ingest(PLACE, _listing("Example Lettings Group Ltd"))
    assert evidence == []
    [f] = reconcile(claims, evidence, OK)
    assert f.verdict == "unverifiable"
    assert "no exact Companies House match for Example Lettings Group Ltd" in f.reasoning


def test_no_key_or_offline_is_off_not_error(tmp_path, monkeypatch):
    with pytest.raises(SourceOff):
        ch.ingest(PLACE, _listing())
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    r = run_xray(build_gateway(Store(tmp_path / "s.json")), "demo", offline=True)
    status = {s.name: s.status for s in r.sources}
    assert status["companies_house"] == "off"
    assert not any(f.field == "companies_house" for f in r.findings)
