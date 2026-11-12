"""explain_finding and get_place_graph answer from the run's cited evidence only."""

from starter.core.gateway import build_gateway
from starter.core.store import Store
from starter.runtime import mcp_door
from starter.verticals.xray import place_graph, run_xray


def _run(tmp_path):
    gateway = build_gateway(Store(tmp_path / "s.json"))
    return gateway, run_xray(gateway, "demo", offline=True)


def _call(gateway, tool, **args):
    return gateway.call(tool, args, "test")["payload"]


def test_a_finding_is_explained_from_its_cited_evidence_only(tmp_path):
    gateway, r = _run(tmp_path)
    f = next(f for f in r.findings if f.field == "property_type")
    out = _call(gateway, "explain_finding", finding_id=f.id)
    assert out["finding"]["id"] == f.id and out["claim"]["id"] == f.claim_id
    assert [e["id"] for e in out["evidence"]] == f.evidence_ids
    for e in out["evidence"]:
        assert e["source_url"] in out["answer"] and str(e["value"]) in out["answer"]
    assert str(out["claim"]["value"]) in out["answer"] and f.reasoning not in out["answer"]


def test_a_run_id_explains_the_score_with_each_cost_and_its_url(tmp_path):
    gateway, r = _run(tmp_path)
    out = _call(gateway, "explain_finding", finding_id=r.run_id)
    assert out["trust_score"] == r.trust_score and f"Trust Score {r.trust_score}" in out["answer"]
    costly = [
        f.id for f in r.findings if f.verdict in ("disagrees", "flag") and f.severity != "info"
    ]
    assert [c["finding"]["id"] for c in out["costs"]] == costly and costly
    assert all(c["source_urls"] and c["source_urls"][0] in out["answer"] for c in out["costs"])


def test_explaining_over_mcp_counts_on_the_run(tmp_path):
    gateway, r = _run(tmp_path)
    token = mcp_door.CLIENT.set("cursor")
    try:
        _call(gateway, "explain_finding", finding_id=r.run_id)
    finally:
        mcp_door.CLIENT.reset(token)
    _call(gateway, "explain_finding", finding_id=r.run_id)  # not over MCP: not counted
    run = gateway.store.snapshot()["xray_runs"][r.run_id]
    assert run["client_calls"]["mcp"]["cursor"] == 1


def test_get_place_graph_is_the_route(tmp_path):
    gateway, r = _run(tmp_path)
    assert _call(gateway, "get_place_graph", place_id=r.place_id) == place_graph(
        r.place_id, gateway.store
    )
