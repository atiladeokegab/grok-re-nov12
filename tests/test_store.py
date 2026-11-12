import threading

import pytest


def test_mutate_persists_and_bumps_version(store):
    assert store.snapshot() == {"version": 0, "events": []}
    store.mutate(lambda d: d.update(items=[1]))
    assert store.snapshot()["items"] == [1]
    assert store.snapshot()["version"] == 1


def test_failing_mutation_leaves_file_unchanged(store):
    store.mutate(lambda d: d.update(items=[1]))
    before = store.path.read_bytes()

    def boom(data):
        data["items"].append(2)
        raise RuntimeError("halfway")

    with pytest.raises(RuntimeError):
        store.mutate(boom)
    assert store.path.read_bytes() == before


def test_publish_numbers_events(store):
    first = store.publish({"type": "a"})
    second = store.publish({"type": "b"})
    assert (first["seq"], second["seq"]) == (1, 2)
    assert [e["type"] for e in store.snapshot()["events"]] == ["a", "b"]


def test_concurrent_mutations_do_not_lose_writes(store):
    def bump(data):
        data["n"] = data.get("n", 0) + 1

    threads = [
        threading.Thread(target=lambda: [store.mutate(bump) for _ in range(20)]) for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.snapshot()["n"] == 100
