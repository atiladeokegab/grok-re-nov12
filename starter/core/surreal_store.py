"""SurrealStore: the Store contract on one SurrealDB record, chosen with STORE=surreal (see config).

The whole state is one JSON string on the record starter_state:main, beside its version. The JSON
string is deliberate: SurrealDB drops fields set to null, so a native object would not read back
what was written. mutate reads, runs fn, and writes with one UPSERT that only matches while the
version is still the one fn saw; on a clash it rereads and runs fn again, so fn must only change
`data`. A raising fn writes nothing. The same connection (`.db`) serves SurrealQL for anything
beyond the store, such as graph relations; see the README.
"""

import copy
import json
import random
import time
from collections.abc import Callable
from typing import TypeVar

from surrealdb import ServerError, Surreal

from starter.core.errors import ConflictError
from starter.core.store import EMPTY, Store

T = TypeVar("T")
RECORD = "starter_state:main"
# One statement is one transaction. `version ?? 0` is 0 when the record does not exist yet, so the
# first write creates it and every later one is a compare-and-swap on the version.
CAS = (
    f"UPSERT {RECORD} SET version = $next, json = $json WHERE (version ?? 0) = $prev"
    " RETURN VALUE version"
)


class SurrealStore(Store):
    # ponytail: every write rewrites the whole document, like GcsStore; split state into records
    # per key when the event log grows past a few MB or writes queue.

    def __init__(
        self,
        url: str,
        namespace: str,
        database: str,
        username: str | None = None,
        password: str | None = None,
        tries: int = 8,
    ):
        self.db = Surreal(url)  # mem:// runs embedded in this process; ws(s):// is a server
        if username:
            self.db.signin({"username": username, "password": password})
        self.db.use(namespace, database)
        self.tries = tries

    def snapshot(self) -> dict:
        doc = self.db.query(f"SELECT VALUE json FROM ONLY {RECORD}")
        return json.loads(doc) if doc else copy.deepcopy(EMPTY)

    def mutate(self, fn: Callable[[dict], T]) -> T:
        for attempt in range(self.tries):
            data = self.snapshot()
            prev = data.get("version", 0)
            result = fn(data)
            data["version"] = prev + 1
            try:
                vars = {"prev": prev, "next": prev + 1, "json": json.dumps(data)}
                if self.db.query(CAS, vars):
                    return result
            except ServerError as e:  # a server's own write-write clash is retryable too
                if "conflict" not in str(e).lower():
                    raise
            time.sleep(random.uniform(0, 0.05 * 2**attempt))  # someone wrote first: back off
        raise ConflictError(f"store kept changing underneath; gave up after {self.tries} tries")
