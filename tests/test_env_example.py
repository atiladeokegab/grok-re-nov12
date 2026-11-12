"""Local and production config stay in step: .env.example lists exactly what config.py reads."""

import re
from pathlib import Path

from starter.runtime.config import Settings

ROOT = Path(__file__).resolve().parent.parent
# env.get("X"), env["X"], os.environ.get("X"), os.getenv("X"): every way config.py reads a name.
READ = re.compile(
    r"""(?:env(?:iron)?\.get\(|env(?:iron)?\[|getenv\()\s*["']([A-Z][A-Z0-9_]*)["']"""
)


def names_read() -> set[str]:
    return set(READ.findall((ROOT / "starter/runtime/config.py").read_text()))


def listed() -> dict[str, str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    pairs = [ln.split("=", 1) for ln in lines if "=" in ln and not ln.lstrip().startswith("#")]
    return {name.strip(): value.strip() for name, value in pairs}


def names_listed() -> set[str]:
    return set(listed())


def test_config_reads_something():
    assert {"MODE", "ANTHROPIC_API_KEY"} <= names_read()  # the parser still finds the reads


def test_every_name_config_reads_is_in_env_example():
    missing = names_read() - names_listed()
    assert not missing, f"config.py reads {sorted(missing)}: add them to .env.example"


def test_env_example_lists_no_name_config_dropped():
    stale = names_listed() - names_read()
    assert not stale, f".env.example lists {sorted(stale)}, which config.py no longer reads"


def test_env_example_values_are_the_local_defaults():
    assert Settings.from_env(listed()) == Settings.from_env({})
