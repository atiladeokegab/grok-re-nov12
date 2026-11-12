"""The one store: a JSON file, locked with flock and replaced atomically; or, when DATA_PATH is
gs://bucket/object, one GCS object written with compare-and-swap (GcsStore), so state survives a
deploy and more than one instance can write.

snapshot() reads, mutate(fn) is the only way to write, publish(event) appends to the event log
that drives the audit trail and the runs page. Every successful mutate bumps data["version"].
"""

import copy
import fcntl
import json
import os
import random
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from google.api_core.exceptions import NotFound, PreconditionFailed

from starter.core.errors import ConflictError

T = TypeVar("T")
EMPTY = {"version": 0, "events": []}
_object_locks: dict[str, threading.RLock] = {}  # gs://bucket/object -> writers in this process


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def snapshot(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return copy.deepcopy(EMPTY)

    def mutate(self, fn: Callable[[dict], T]) -> T:
        """Run fn on a copy of the data under an exclusive lock; write only if fn returns."""
        # ponytail: one lock for the whole store; shard by key if writes ever queue.
        with open(self._lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.snapshot()
            result = fn(data)
            data["version"] = data.get("version", 0) + 1
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".store-")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            return result

    def publish(self, event: dict) -> dict:
        """Append an event with a sequence number and timestamp; return it as stored."""

        def append(data: dict) -> dict:
            events = data.setdefault("events", [])
            stored = {"seq": len(events) + 1, "ts": time.time(), **event}
            events.append(stored)
            return stored

        return self.mutate(append)


class GcsStore(Store):
    """The Store contract on one GCS object. mutate reads the object and its generation, runs fn,
    and writes only if the generation is unchanged; on a clash it rereads and runs fn again, so
    fn must only change `data`. A raising fn writes nothing."""

    # ponytail: every write rewrites the whole object and GCS allows about one write per second
    # per object, so this holds a demo's few writes a second, not more; shard objects by key, or
    # move to Firestore, when writes queue or the event log grows past a few MB.

    def __init__(self, url: str, client=None, tries: int = 8):
        bucket, _, self.name = url.removeprefix("gs://").partition("/")
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket = client.bucket(bucket)
        self.tries = tries
        # One writer per object per process: parallel source threads queue here instead of racing
        # the generation check; CAS then only arbitrates between instances. Reentrant, so a write
        # from inside fn (tests simulate another instance that way) does not deadlock.
        self._lock = _object_locks.setdefault(url, threading.RLock())

    def _read(self) -> tuple[dict, int]:
        """(data, generation); generation 0 means no object yet, which is what GCS matches."""
        blob = self.bucket.blob(self.name)  # a fresh handle per read: safe across threads
        try:
            return json.loads(blob.download_as_bytes()), blob.generation
        except NotFound:
            return copy.deepcopy(EMPTY), 0

    def snapshot(self) -> dict:
        return self._read()[0]

    def mutate(self, fn: Callable[[dict], T]) -> T:
        with self._lock:
            return self._mutate(fn)

    def _mutate(self, fn: Callable[[dict], T]) -> T:
        for attempt in range(self.tries):
            data, generation = self._read()
            result = fn(data)
            data["version"] = data.get("version", 0) + 1
            try:
                self.bucket.blob(self.name).upload_from_string(
                    json.dumps(data, indent=1),
                    content_type="application/json",
                    if_generation_match=generation,
                )
                return result
            except PreconditionFailed:  # another instance wrote first: back off, reread, retry
                time.sleep(random.uniform(0.05, 0.2 * 2 ** min(attempt, 4)))
        raise ConflictError(f"store kept changing underneath; gave up after {self.tries} tries")


def open_store(path: str, client=None) -> Store:
    """GcsStore for a gs:// path, else the local JSON file."""
    return GcsStore(path, client) if str(path).startswith("gs://") else Store(path)
