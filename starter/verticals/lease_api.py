"""The office lease beat over HTTP and MCP.

GET /api/lease/eval is the committed per-field accuracy (docs/lease-eval.json); POST
/api/lease/abstract reads an uploaded .docx in memory and returns the abstraction plus the
X-ray contract objects. The upload is never written to disk or the store.
"""

import io
import json
import zipfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, UploadFile

from starter.core.errors import NotFound
from starter.verticals.lease import abstract, contract

router = APIRouter(tags=["lease"])
EVAL = Path(__file__).resolve().parents[2] / "docs/lease-eval.json"
MAX_BYTES = 5 * 1024 * 1024


def eval_results() -> dict:
    if not EVAL.exists():
        raise NotFound("no lease eval results committed (run make eval-leases)")
    return json.loads(EVAL.read_text())


@router.get("/api/lease/eval")
def lease_eval() -> dict:
    """Per-field accuracy of the lease extractor on the hand-labelled MCL gold set."""
    return eval_results()


@router.post("/api/lease/abstract")
async def lease_abstract(file: UploadFile) -> dict:
    """Abstract an uploaded .docx lease (max 5 MB): head terms, place, evidence and findings."""
    name = Path(file.filename or "").name
    if not name.lower().endswith(".docx"):
        raise ValueError("upload a .docx lease")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("lease too large: the limit is 5 MB")
    try:
        terms = abstract(io.BytesIO(data))
        place, evidence, findings = contract(io.BytesIO(data), Path(name).stem)
    except (zipfile.BadZipFile, KeyError, ParseError) as e:
        raise ValueError(f"not a readable .docx: {e}") from e
    return {
        "terms": terms,
        "place": place.model_dump(),
        "evidence": [e.model_dump() for e in evidence],
        "findings": [f.model_dump() for f in findings],
    }


def register_tools(gateway) -> None:
    @gateway.register(effect=False)
    def abstract_lease_eval() -> dict:
        """Per-field accuracy of the office lease abstraction on the organisers' hand-labelled
        Model Commercial Lease gold set (in-sample): n, strict and content correct per field."""
        r = eval_results()
        return {"documents": r["documents"], "fields": r["fields"], "overall": r["overall"]}
