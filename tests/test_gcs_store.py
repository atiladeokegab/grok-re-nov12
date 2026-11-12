"""GcsStore: the Store contract on one GCS object, with compare-and-swap on its generation.
A fake client stands in for google-cloud-storage, so no test touches the network."""

import json

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from starter.core.errors import ConflictError
from starter.core.store import GcsStore, Store, open_store
from starter.runtime.config import Settings

URL, NAME = "gs://demo-bucket/state/store.json", "state/store.json"


class FakeBucket:
    """One bucket's objects as {name: (bytes, generation)}, and the client calls GcsStore makes."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, int]] = {}
        self.uploads = 0
        self.before_upload = None  # hook: runs once before the next upload, to race it

    def bucket(self, name):
        assert name == "demo-bucket"
        return self

    def blob(self, name):
        return FakeBlob(self, name)


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str):
        self.bucket, self.name, self.generation = bucket, name, None

    def download_as_bytes(self) -> bytes:
        if self.name not in self.bucket.objects:
            raise NotFound("no such object")
        data, self.generation = self.bucket.objects[self.name]
        return data

    def upload_from_string(self, data, content_type, if_generation_match):
        if hook := self.bucket.before_upload:
            self.bucket.before_upload = None
            hook()
        current = self.bucket.objects.get(self.name, (b"", 0))[1]
        if current != if_generation_match:
            raise PreconditionFailed("generation changed")
        self.bucket.uploads += 1
        self.bucket.objects[self.name] = (data.encode(), current + 1)
        assert content_type == "application/json"


@pytest.fixture
def fake():
    return FakeBucket()


@pytest.fixture
def gcs(fake):
    return GcsStore(URL, client=fake)


def test_same_contract_as_the_local_store(gcs, fake):
    assert gcs.snapshot() == {"version": 0, "events": []}
    gcs.mutate(lambda d: d.update(items=[1]))
    assert gcs.snapshot()["items"] == [1] and gcs.snapshot()["version"] == 1
    first, second = gcs.publish({"type": "a"}), gcs.publish({"type": "b"})
    assert (first["seq"], second["seq"]) == (1, 2)
    assert json.loads(fake.objects[NAME][0])["version"] == 3


def test_a_conflicting_write_is_retried_on_fresh_data(gcs, fake):
    gcs.mutate(lambda d: d.update(n=1))
    other = GcsStore(URL, client=fake)
    fake.before_upload = lambda: other.mutate(lambda d: d.update(n=d["n"] + 10))

    gcs.mutate(lambda d: d.update(n=d["n"] + 1))
    assert gcs.snapshot()["n"] == 12  # both writes kept: 1 + 10 + 1
    assert gcs.snapshot()["version"] == 3


def test_retries_are_bounded(fake):
    store = GcsStore(URL, client=fake, tries=5)
    store.mutate(lambda d: None)

    def race():  # another writer gets in before every upload
        data, generation = fake.objects[NAME]
        fake.objects[NAME] = (data, generation + 1)
        fake.before_upload = race

    fake.before_upload = race
    with pytest.raises(ConflictError, match="5 tries"):
        store.mutate(lambda d: d.update(n=1))
    assert "n" not in store.snapshot()


def test_a_failing_fn_leaves_the_object_untouched(gcs, fake):
    gcs.mutate(lambda d: d.update(items=[1]))
    before = fake.objects[NAME]

    def boom(data):
        data["items"].append(2)
        raise RuntimeError("halfway")

    with pytest.raises(RuntimeError):
        gcs.mutate(boom)
    assert fake.objects[NAME] == before and fake.uploads == 1


def test_data_path_picks_the_store(tmp_path, fake):
    assert Settings.from_env({"DATA_PATH": URL}).data_path == URL  # not collapsed to gs:/
    assert type(open_store(str(tmp_path / "store.json"))) is Store
    assert type(open_store("gs://demo-bucket/store.json", client=fake)) is GcsStore


def test_parallel_source_threads_all_land(fake, monkeypatch):
    """Nine source threads writing at once (the live ConflictError): every write lands, none gives up."""
    import threading
    import time as _time

    slow_read = FakeBlob.download_as_bytes

    def download(self):  # widen the read->upload window so unserialised writers would clash
        data = slow_read(self)
        _time.sleep(0.002)
        return data

    monkeypatch.setattr(FakeBlob, "download_as_bytes", download)
    store = GcsStore(URL, client=fake, tries=2)
    errors = []

    def source(i):
        try:
            for _ in range(5):
                store.publish({"type": "xray", "source": i})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=source, args=(i,)) for i in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.snapshot()["events"]) == 45
