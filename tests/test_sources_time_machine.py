from starter.core.gateway import build_gateway
from starter.core.ingest import decoded_text
from starter.core.store import Store
from starter.verticals.xray import run_xray


def test_recorded_epc_history_is_grounded_and_does_not_change_current_score(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "documents"))
    report = run_xray(build_gateway(Store(tmp_path / "state.json")), "macquarie", offline=True)
    historical = [e for e in report.evidence if e.agent == "epc_history"]
    assert len(historical) == 3
    assert {e.observed_at for e in historical} == {"2020-02-29"}
    assert report.counts.matches == 1 and report.counts.disagrees == 1
    assert report.trust_score == 67
    documents = {d.id: d for d in report.documents}
    for evidence in historical:
        text = decoded_text(documents[evidence.document_id])
        assert text[evidence.span.start : evidence.span.end] == evidence.span.quote
        assert not any(evidence.id in f.evidence_ids for f in report.findings)
    assert any(h.agent == "epc_history" and h.value == 84 for h in report.history)
