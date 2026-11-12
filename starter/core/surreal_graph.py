"""The place graph in an embedded SurrealDB (mem://, inside this process): each saved run is
loaded once as records joined by RELATE edges, and /api/place/{id}/graph is answered by ONE
SurrealQL query.

The JSON/GCS store stays the store of record; this is a read-side graph rebuilt from it. If
SurrealDB cannot start or a query fails, callers fall back to building the graph in Python.
"""

import json
import logging
import threading

log = logging.getLogger(__name__)
EDGES = ("has", "landed", "contains", "checked_by", "cites")
_RELATE = " ELSE ".join(
    f"IF $e.kind = '{k}' {{ RELATE (type::thing($e.fk, [$run, $e.from]))"
    f"->{k}->(type::thing($e.tk, [$run, $e.to]))"
    " SET run = $run; }"
    for k in EDGES
)
LOAD = (
    "FOR $n IN $nodes { UPSERT type::thing($n.kind, [$run, $n.id]) SET run = $run, key = $n.id,"
    " json = $n.json; };"
    f" FOR $e IN $edges {{ {_RELATE}; }};"
)
# Records are keyed [run, id]: two runs of one place share ids. The panel prints this query.
QUERY = (
    "SELECT (SELECT key AS id, record::tb(id) AS kind, json"
    " FROM place, claim, evidence, finding, document WHERE run = $run) AS nodes,"
    " (SELECT in.key AS from, out.key AS to, record::tb(id) AS kind"
    f" FROM {', '.join(EDGES)} WHERE run = $run) AS edges"
    " FROM ONLY type::thing('place', [$run, $place])"
)


class Graph:
    def __init__(self):
        from surrealdb import Surreal

        self.db = Surreal("mem://")
        self.db.use("xray", "graph")
        self._lock = threading.Lock()
        self._loaded: set[str] = set()

    def answer(self, place_id: str, run_id: str, nodes: list[dict], edges: list[dict]) -> dict:
        """Load the run once (nodes/edges as built from the saved report), then query it back."""
        with self._lock:
            if run_id not in self._loaded:
                kind = {n["id"]: n["kind"] for n in nodes}
                self.db.query(
                    LOAD,
                    {
                        "run": run_id,
                        "nodes": [
                            {"kind": n["kind"], "id": n["id"], "json": json.dumps(n["data"])}
                            for n in nodes
                        ],
                        "edges": [
                            {**e, "fk": kind[e["from"]], "tk": kind[e["to"]]}
                            for e in edges
                            if e["from"] in kind and e["to"] in kind
                        ],
                    },
                )
                self._loaded.add(run_id)
            got = self.db.query(QUERY, {"run": run_id, "place": place_id})
        return {
            "nodes": [
                {"id": n["id"], "kind": n["kind"], "data": json.loads(n["json"])}
                for n in got["nodes"]
            ],
            "edges": got["edges"],
        }


_graph: Graph | None = None
_failed = False


def graph() -> Graph | None:
    """The process's embedded graph, or None when SurrealDB can't start here (callers fall back)."""
    global _graph, _failed
    if _graph is None and not _failed:
        try:
            _graph = Graph()
        except Exception as e:  # never break the demo: no SurrealDB means the Python graph
            _failed = True
            log.warning("embedded SurrealDB unavailable, graph falls back to Python: %s", e)
    return _graph
