"""Narration rewrites wording only, and drops a line that brings in a number of its own."""

from starter.core.xray import Claim, Evidence, Finding
from starter.verticals import narrate


def _case():
    c = Claim(id="c1", place_id="p", field="floor_area", value=70, unit="m2")
    e = Evidence(
        id="e1",
        place_id="p",
        field="floor_area",
        value=52.0,
        unit="m2",
        source_name="EPC register",
        agent="epc",
    )
    f = Finding(
        id="f1",
        place_id="p",
        field="floor_area",
        verdict="disagrees",
        severity="high",
        claim_id="c1",
        evidence_ids=["e1"],
        reasoning="rules line",
        model="rules",
    )
    return f, c, e


def test_offline_keeps_rules(monkeypatch):
    f, c, e = _case()
    assert narrate.narrate([f], [c], [e])["calls"] == 0 and f.model == "rules"


def test_model_line_kept_only_when_its_numbers_come_from_evidence(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "x")
    f, c, e = _case()
    monkeypatch.setattr(narrate, "_ask", lambda *a: '{"f1": "Advert says 70 m2; register 52 m2."}')
    assert narrate.narrate([f], [c], [e])["provider"] == "xai"
    assert f.reasoning.startswith("Advert says 70") and f.verdict == "disagrees"
    f, c, e = _case()
    monkeypatch.setattr(narrate, "_ask", lambda *a: '{"f1": "It is really 99 m2."}')
    narrate.narrate([f], [c], [e])
    assert f.reasoning == "rules line"
