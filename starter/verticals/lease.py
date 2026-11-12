"""Lease abstraction: read a UK commercial lease (.docx) and pull out the head terms.

Deterministic rules over the Word paragraphs, no model: definitions ("Main Rent" followed by
its meaning), clause headings ("Insurance", "Dealings with the Premises") and the Land
Registry prescribed clauses (LR1-LR14). Each field says whether the template still holds a
placeholder ([●], [ADDRESS OF PREMISES], [   ]) and the words it was read from.
"""

import re
import zipfile
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

from starter.core.xray import Evidence, Finding, Place

FIELDS = [
    "parties",
    "premises",
    "permitted_use",
    "contractual_term",
    "main_rent",
    "rent_review",
    "break_clause",
    "alienation",
    "insurance",
    "lr_prescribed_clauses",
]

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# [●], [   ], or an all-caps blank such as [ADDRESS OF PREMISES] / [AMOUNT IN WORDS].
PLACEHOLDER = re.compile(r"\[\s*(?:●|[A-Z][A-Z0-9 ,/&’'().\-]*[A-Z0-9)]|)\s*\]")
_DEF = re.compile(r'^(\[?)\s*[“"]([^”"]+)[”"]\s*\]?$')  # a definition term on its own line
_LR = re.compile(r"^LR(\d{1,2})\.\s")


def paragraphs(path: str | Path | IO[bytes]) -> list[str]:
    """Non-empty paragraph texts of a .docx, in order (stdlib only)."""
    z = zipfile.ZipFile(path)
    if z.getinfo("word/document.xml").file_size > 50 * 1024 * 1024:  # uploads: no zip bombs
        raise ValueError("word/document.xml is over 50 MB uncompressed")
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(_W + "p"):
        text = "".join(t.text or "" for t in p.iter(_W + "t")).strip()
        if text:
            out.append(text)
    return out


def _run_on(paras: list[str], i: int) -> str:
    """Paragraph i, plus its list items when it ends "including:", "; or" or "and"."""
    text = [paras[i]]
    for q in paras[i + 1 : i + 5]:
        if _DEF.match(q) or not re.search(r"(:|\bor|\band)$", text[-1]):
            break
        text.append(q)
    return " ".join(text)


def _definition(paras: list[str], *terms: str) -> tuple[str, str, bool] | None:
    """(term, meaning, optional) for the first defined term found; optional = bracketed."""
    for term in terms:
        for i, p in enumerate(paras[:-1]):
            m = _DEF.match(p)
            if m and m.group(2).strip().lower() == term.lower():
                return term, _run_on(paras, i + 1), bool(m.group(1))
    return None


def _heading(paras: list[str], *headings: str) -> tuple[str, str, bool] | None:
    """(heading, body, optional) for every paragraph equal to the first heading that occurs.

    A lease repeats a heading per party (tenant's and landlord's "Insurance"), so all
    occurrences are kept.
    """
    for h in headings:
        idx = [i for i, p in enumerate(paras[:-1]) if p.lstrip("[").strip().lower() == h.lower()]
        if idx:
            body = " / ".join(_run_on(paras, i + 1) for i in idx)
            return paras[idx[0]].lstrip("["), body, paras[idx[0]].startswith("[")
    return None


def _schedule(paras: list[str], title: str) -> tuple[str, str, bool] | None:
    """(title, its sub-headings) for a schedule: short unpunctuated lines that follow it.

    Skips "Interpretation"/"Definitions", which say nothing about the subject.
    shortcut: the window is a fixed 50 paragraphs, since schedule ends are not marked in the
    body text; upgrade by reading the Word heading styles if schedules run together.
    """
    for i, p in enumerate(paras):
        if p.lower() == title.lower():
            subs = [
                q
                for q in paras[i + 1 : i + 51]
                if len(q) <= 60
                and q[0].isupper()
                and not re.search(r"[.;:,\]]$", q)
                and q not in ("Interpretation", "Definitions")
            ]
            return p, "; ".join(subs), False
    return None


def _block(paras: list[str], start: str, stop: str) -> tuple[str, str, bool] | None:
    """(heading, text) of the paragraphs after a heading up to the next stop heading."""
    for i, p in enumerate(paras):
        if re.match(start, p):
            body = []
            for q in paras[i + 1 : i + 9]:
                if re.match(stop, q):
                    break
                body.append(q)
            return p, " ".join(body), False
    return None


def _field(value: str | None, source: str | None, optional: bool = False) -> dict:
    return {
        "value": value,
        "placeholder": bool(value and PLACEHOLDER.search(value)),
        "optional": optional,
        "source": source,
        "doc_span": (value[:160] + "…" if len(value) > 160 else value) if value else None,
    }


def _join(*parts: tuple[str, str, bool] | None) -> tuple[str | None, str | None, bool]:
    """Merge several (heading, text, optional) hits into one field value."""
    hits = [p for p in parts if p]
    if not hits:
        return None, None, False
    value = " | ".join(f"{h}: {t}" for h, t, _ in hits)
    return value, "; ".join(h for h, _, _ in hits), hits[0][2]


def abstract(path: str | Path | IO[bytes]) -> dict:
    """{field: {value, placeholder, optional, source, doc_span}} for the nine head terms + LR."""
    paras = paragraphs(path)
    out: dict[str, dict] = {}

    parties = _block(paras, r"LR3\. Parties", r"LR4\.") or _block(paras, "PARTIES$", "IT IS AGREED")
    out["parties"] = _field(parties[1], parties[0]) if parties else _field(None, None)

    for name, terms in [
        ("premises", ("Premises",)),
        ("permitted_use", ("Permitted Use",)),
        ("contractual_term", ("Contractual Term", "Term Commencement Date")),
        ("main_rent", ("Main Rent",)),
    ]:
        hit = _definition(paras, *terms)
        out[name] = _field(hit[1], f"definition “{hit[0]}”", hit[2]) if hit else _field(None, None)

    composite = {
        "rent_review": (_definition(paras, "Rent Review Date"), _heading(paras, "Rent review")),
        "break_clause": (_heading(paras, "BREAK CLAUSE"), _definition(paras, "Break Date")),
        "alienation": (
            _block(paras, r"LR8\.", r"LR9\."),
            _heading(paras, "Dealings with the Premises", "Dealings with this Agreement"),
            _heading(paras, "Disposals"),
            _heading(paras, "Underletting"),
        ),
        "insurance": (
            _heading(paras, "Insurance", "Insurance and risk"),
            _schedule(paras, "Insurance and Damage Provisions"),
        ),
    }
    for name, hits in composite.items():
        value, source, optional = _join(*hits)
        out[name] = _field(value, source, optional)

    lr = sorted({int(m.group(1)) for p in paras if (m := _LR.match(p)) and int(m.group(1)) <= 14})
    found = f"{len(lr)} of 14 prescribed clauses present: LR{', LR'.join(map(str, lr))}"
    out["lr_prescribed_clauses"] = _field(found if lr else None, "LR1-LR14" if lr else None)
    return out


def contract(
    path: str | Path | IO[bytes], name: str | None = None
) -> tuple[Place, list[Evidence], list[Finding]]:
    """The abstraction as X-ray contract objects: one Evidence and one Finding per field."""
    sample = name or Path(path).stem
    terms = abstract(path)
    premises = terms["premises"]["value"] or ""
    place = Place(
        id=f"place-lease-{sample.lower()}", address=premises[:200], postcode="", use="office"
    )
    evidence, findings = [], []
    for field, t in terms.items():
        fid = f"{sample.lower()}-{field}"
        if t["value"] is None:
            findings.append(
                Finding(
                    id=f"f-{fid}",
                    place_id=place.id,
                    field=field,
                    verdict="unverifiable",
                    reasoning=f"No {field.replace('_', ' ')} clause found in the lease.",
                    model="rules",
                )
            )
            continue
        evidence.append(
            Evidence(
                id=f"e-{fid}",
                place_id=place.id,
                field=field,
                value=t["value"],
                source_name=f"Model Commercial Lease {sample}",
                doc_span=t["doc_span"],
                agent="lease",
            )
        )
        state = "still a template placeholder" if t["placeholder"] else "found"
        opt = " (optional clause)" if t["optional"] else ""
        label = field.replace("_", " ").capitalize()
        findings.append(
            Finding(
                id=f"f-{fid}",
                place_id=place.id,
                field=field,
                verdict="flag",
                severity="info",
                evidence_ids=[f"e-{fid}"],
                reasoning=f"{label} {state}{opt}, from {t['source']}.",
                model="rules",
            )
        )
    return place, evidence, findings
