"""Turning a case folder into model input. The outcome section is the answer key: it is cut here,
before anything else sees the text, and tests/test_no_leak.py proves it stays cut."""

import re
from pathlib import Path

OUTCOME = re.compile(r"^## Outcome\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
CASE_FILES = ("index.md", "history.md")


def strip_outcome(text: str) -> str:
    return OUTCOME.sub("", text).strip()


def load_case(folder: Path) -> dict:
    """{"id": folder name, "body": index.md + history.md with every outcome section removed}."""
    parts = [(folder / name).read_text() for name in CASE_FILES if (folder / name).exists()]
    return {"id": folder.name, "body": strip_outcome("\n\n".join(parts))}
