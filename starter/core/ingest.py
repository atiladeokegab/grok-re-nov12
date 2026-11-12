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


def docs_dir() -> Path:
    if d := os.environ.get("DOCS_DIR"):
        return Path(d)
    data = os.environ.get("DATA_PATH", "data/store.json")
    # shortcut: with DATA_PATH on gs:// documents live on the instance's /tmp, so each Cloud Run
    # instance only serves what it landed; move them to the bucket when runs span instances.
    if data.startswith("gs://"):
        return Path("/tmp/xray-documents")
    return Path(data).parent / "documents"


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
    path = docs_dir() / sha
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    doc = Document(
        id=f"doc-{sha[:16]}",
        url=source_url,
        sha256=sha,
        content_type=content_type,
        fetched_at=fetched_at or now(),
        agent=agent,
        size=len(data),
        bytes_path=str(path),
    )
    docs.append(doc)
    return doc


def raw_bytes(doc: Document | dict) -> bytes:
    path = doc.bytes_path if isinstance(doc, Document) else doc["bytes_path"]
    return Path(path).read_bytes()


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
