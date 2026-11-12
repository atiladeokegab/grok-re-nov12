"""Model-written reasoning: one batched call rewrites each non-match finding's template line in
plain English for a renter. The model sees only the claim and the cited evidence, may not change
a verdict, and a line that names a number the evidence does not contain is thrown away (the
rules line stays). Provider: xAI Grok when XAI_API_KEY is set, else Claude when
ANTHROPIC_API_KEY is set, else none (offline: rules text, model "rules").
"""

import json
import os
import re

import httpx2 as httpx

from starter.core.xray import Claim, Evidence, Finding
from starter.runtime.config import XAI_MODEL

TIMEOUT_S = 12  # narration is garnish: past this the rules lines stand, so "done" stays fast
XAI_URL = "https://api.x.ai/v1/chat/completions"
PROMPT = (
    "You explain property-listing checks to a renter. For each finding, write ONE plain sentence "
    "(max 30 words) saying what the advert claims and what the cited source records. Use only "
    "the values given; never add facts, never say fraud, fake or AI-generated, never change the "
    'verdict. Reply with JSON only: {"<finding id>": "<sentence>", ...}.'
)


def provider() -> tuple[str, str] | None:
    """(provider, model) for narration, or None offline."""
    if os.environ.get("XAI_API_KEY"):
        return "xai", (os.environ.get("XAI_MODEL") or XAI_MODEL)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", os.environ.get("MODEL", "claude-opus-5-5")
    return None


def _ask(kind: str, model: str, payload: str) -> str:
    if kind == "xai":
        r = httpx.post(
            XAI_URL,
            headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": payload},
                ],
            },
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    import anthropic

    msg = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0).messages.create(
        model=model,
        max_tokens=1500,
        system=PROMPT,
        messages=[{"role": "user", "content": payload}],
    )
    return msg.content[0].text


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def narrate(findings: list[Finding], claims: list[Claim], evidence: list[Evidence]) -> dict:
    """Rewrite reasoning in place. Returns {"provider", "model", "calls", "error"}."""
    chosen = provider()
    targets = [f for f in findings if f.verdict in ("disagrees", "flag") and f.evidence_ids]
    if not chosen or not targets:
        return {"provider": None, "model": "rules", "calls": 0, "error": None}
    kind, model = chosen
    by_id = {e.id: e for e in evidence} | {c.id: c for c in claims}
    items = []
    for f in targets:
        claim = by_id.get(f.claim_id) if f.claim_id else None
        items.append(
            {
                "id": f.id,
                "field": f.field,
                "verdict": f.verdict,
                "advert": claim.model_dump(include={"value", "unit", "doc_span"})
                if claim
                else None,
                "sources": [
                    by_id[i].model_dump(include={"source_name", "value", "unit", "doc_span"})
                    for i in f.evidence_ids
                    if i in by_id
                ],
            }
        )
    try:
        text = _ask(kind, model, json.dumps(items))
        lines = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except Exception as e:  # narration is garnish: the rules lines stand
        return {"provider": kind, "model": model, "calls": 1, "error": f"{type(e).__name__}: {e}"}
    for f, item in zip(targets, items, strict=True):
        line = lines.get(f.id)
        allowed = _numbers(json.dumps(item))
        if isinstance(line, str) and 0 < len(line) <= 300 and _numbers(line) <= allowed:
            f.reasoning, f.model = line.strip(), model
    return {"provider": kind, "model": model, "calls": 1, "error": None}
