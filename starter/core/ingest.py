"""Traceable ingestion (contract: hub ingest-contract v1): land the raw original, ground quotes.

land() stores a source's raw bytes under their sha256 and records the Document on the run
(listing["_documents"]); ground() finds a verbatim quote in a document's decoded text, repairing
whitespace, or returns None so the quote is dropped rather than shown unverified.
"""

import hashlib
import html
import json
import os
import re
from pathlib import Path

from starter.core.xray import Document, Span, now

TEXT_CAP = 200_000
__all__ = ["Document", "Span", "decoded_text", "ground", "land", "raw_bytes"]


# Same as starter.verticals.sources.web.visible_text; copied, not imported, because sources import
# this module and importing the sources package from here would be circular.
def visible_text(page: str) -> str:
    """The words a reader sees: scripts, styles and tags removed, whitespace collapsed."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


CACHE_DIR = Path("/tmp/xray-documents")  # per-instance copy of documents kept in the bucket
_client = None  # the google-cloud-storage client, made on first use; tests put a fake here


def _bucket(name: str):
    global _client
    if _client is None:
        from google.cloud import storage

        _client = storage.Client()
    return _client.bucket(name)


def docs_dir() -> Path | str:
    """DOCS_DIR, else gs://<bucket>/documents when DATA_PATH is on GCS (shared by every
    instance), else a documents folder beside DATA_PATH."""
    if d := os.environ.get("DOCS_DIR"):
        return Path(d)
    data = os.environ.get("DATA_PATH", "data/store.json")
    if data.startswith("gs://"):
        return f"gs://{data.removeprefix('gs://').partition('/')[0]}/documents"
    return Path(data).parent / "documents"


def _write(where: Path | str, sha: str, data: bytes) -> str:
    if isinstance(where, Path):
        where.mkdir(parents=True, exist_ok=True)
        if not (where / sha).exists():
            (where / sha).write_bytes(data)
        return str(where / sha)
    from google.api_core.exceptions import PreconditionFailed

    bucket, _, prefix = where.removeprefix("gs://").partition("/")
    try:  # generation 0: create only; the same sha256 already there is the same bytes
        _bucket(bucket).blob(f"{prefix}/{sha}").upload_from_string(
            data, content_type="application/octet-stream", if_generation_match=0
        )
    except PreconditionFailed:
        pass
    _write(CACHE_DIR, sha, data)
    return f"{where}/{sha}"


def land(
    listing: dict,
    *,
    raw: bytes | str,
    source_url: str,
    agent: str,
    content_type: str = "text/html",
    fetched_at: str | None = None,
) -> Document:
    data = raw.encode() if isinstance(raw, str) else raw
    sha = hashlib.sha256(data).hexdigest()
    docs = listing.setdefault("_documents", [])
    for d in docs:
        if d.sha256 == sha:
            return d
    path = _write(docs_dir(), sha, data)
    doc = Document(
        id=f"doc-{sha[:16]}",
        url=source_url,
        sha256=sha,
        content_type=content_type,
        fetched_at=fetched_at or now(),
        agent=agent,
        size=len(data),
        bytes_path=path,
    )
    docs.append(doc)
    return doc


def raw_bytes(doc: Document | dict) -> bytes:
    """The stored original; FileNotFoundError if it is gone. gs:// reads go through CACHE_DIR."""
    path = doc.bytes_path if isinstance(doc, Document) else doc["bytes_path"]
    if not path.startswith("gs://"):
        return Path(path).read_bytes()
    from google.api_core.exceptions import NotFound

    bucket, _, name = path.removeprefix("gs://").partition("/")
    cached = CACHE_DIR / name.rpartition("/")[2]
    if cached.exists():
        return cached.read_bytes()
    try:
        data = _bucket(bucket).blob(name).download_as_bytes()
    except NotFound:
        raise FileNotFoundError(path) from None
    _write(CACHE_DIR, cached.name, data)
    return data


def decoded_text(doc: Document | dict) -> str | None:
    """Text for html (visible words), json and plain text; None for anything else or if gone."""
    doc = doc if isinstance(doc, Document) else Document(**doc)
    ctype = doc.content_type.split(";")[0].strip().lower()
    if not (ctype.startswith("text/") or ctype == "application/json"):
        return None
    try:
        text = raw_bytes(doc).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
    if ctype == "text/html":
        text = visible_text(text)
    elif ctype == "application/json":
        text = json.dumps(json.loads(text), indent=1, ensure_ascii=False)
    return text[:TEXT_CAP]


def ground(text: str, quote: str) -> Span | None:
    """Exact find, else whitespace-insensitive find with offsets on `text`; None drops the quote."""
    if not quote or not text:
        return None
    if (i := text.find(quote)) >= 0:
        return Span(start=i, end=i + len(quote), quote=quote)
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), text)
    if m is None:
        return None
    return Span(start=m.start(), end=m.end(), quote=m.group(0))
