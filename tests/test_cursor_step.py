import json
import subprocess

from starter.verticals import cursor_step


def test_no_key_returns_none_without_a_subprocess(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert cursor_step.summarize({"findings": []}) is None


def test_keeps_only_citations_of_known_evidence(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test")
    out = {"summary": "EPC is D, advert says B [ev-1]", "evidence_ids": ["ev-1", "ev-made-up"]}
    done = subprocess.CompletedProcess([], 0, stdout=json.dumps(out))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    before = cursor_step.CALLS["count"]
    result = cursor_step.summarize({"evidence": [{"id": "ev-1"}]})
    assert result["evidence_ids"] == ["ev-1"]
    assert cursor_step.CALLS["count"] == before + 1


def test_a_failed_run_returns_none(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test")

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "node")

    monkeypatch.setattr(subprocess, "run", boom)
    assert cursor_step.summarize({}) is None
