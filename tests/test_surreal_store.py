"""SurrealStore: the Store contract on one SurrealDB record, chosen with STORE=surreal. Every test
runs on the SDK's embedded in-memory engine (mem://), so none needs a server, a key or a network."""

import threading

import pytest

from starter.core.errors import ConflictError
from starter.core.surreal_store import SurrealStore
from starter.runtime.config import Settings
from starter.runtime.factory import create_app


@pytest.fixture
def store():
    return SurrealStore("mem://", "test", "test")


def test_same_contract_as_the_local_store(store):
    assert store.snapshot() == {"version": 0, "events": []}
    store.mutate(lambda d: d.update(items=[1], gone=None))
    assert store.snapshot()["items"] == [1] and store.snapshot()["version"] == 1
    assert store.snapshot()["gone"] is None  # nulls survive: SurrealDB drops NONE fields
    first, second = store.publish({"type": "a"}), store.publish({"type": "b"})
    assert (first["seq"], second["seq"]) == (1, 2)
    assert store.snapshot()["version"] == 3


def test_a_raising_fn_writes_nothing(store):
    def boom(d):
        d["n"] = 1
        raise ValueError("no")

    with pytest.raises(ValueError):
        store.mutate(boom)
    assert store.snapshot() == {"version": 0, "events": []}


def test_a_conflicting_write_is_retried_on_fresh_data(store):
    store.mutate(lambda d: d.update(n=1))
    raced = []

    def add_one(d):
        if not raced:  # another writer lands between this read and this write
            raced.append(True)
            store.mutate(lambda e: e.update(n=e["n"] + 10))
        d["n"] += 1

    store.mutate(add_one)
    assert store.snapshot()["n"] == 12 and store.snapshot()["version"] == 3


def test_gives_up_with_conflict_when_the_record_never_settles(store):
    store.tries = 2
    with pytest.raises(ConflictError):
        store.mutate(lambda d: store.mutate(lambda e: e.update(x=1)))


def test_eight_concurrent_writers_lose_no_update(store):

    def writer():
        for _ in range(25):
            store.mutate(lambda d: d.update(count=d.get("count", 0) + 1))

    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.snapshot()["count"] == 200 and store.snapshot()["version"] == 200


def test_graph_a_fact_is_derived_from_its_source(store):
    store.db.query(
        "CREATE source:brief SET title = 'Event brief';"
        "CREATE fact:deadline SET text = 'Demo at 17:00';"
        "RELATE fact:deadline->derived_from->source:brief;"
    )
    titles = store.db.query("SELECT VALUE ->derived_from->source.title FROM ONLY fact:deadline")
    assert titles == ["Event brief"]


def test_default_store_is_unchanged(tmp_path):
    s = Settings.from_env({"DATA_PATH": str(tmp_path / "store.json")})
    assert s.store == "json"
    app = create_app(s)
    assert not isinstance(app.state.store, SurrealStore)


def test_store_surreal_runs_offline_on_the_embedded_engine():
    s = Settings.from_env({"STORE": "surreal"})
    assert (s.surreal_url, s.surreal_namespace, s.surreal_database) == (
        "mem://",
        "starter",
        "starter",
    )
    assert isinstance(create_app(s).state.store, SurrealStore)


def test_unknown_store_is_rejected():
    with pytest.raises(ValueError, match="STORE"):
        Settings.from_env({"STORE": "postgres"})


def test_cloud_refuses_an_incomplete_surreal_config():
    env = {"MODE": "cloud", "ANTHROPIC_API_KEY": "k", "ADMIN_PASSWORD": "pw", "STORE": "surreal"}
    env["MCP_SECRET"] = "m"
    with pytest.raises(RuntimeError, match="SURREAL_URL, SURREAL_NS, SURREAL_DB, SURREAL_USER"):
        Settings.from_env({**env, "SURREAL_PASS": "p"})
    full = {"SURREAL_URL": "wss://db.example", "SURREAL_NS": "n", "SURREAL_DB": "d"}
    s = Settings.from_env({**env, **full, "SURREAL_USER": "u", "SURREAL_PASS": "secret"})
    assert s.surreal_password == "secret" and "secret" not in str(s.public())
