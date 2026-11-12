"""Skills: small markdown files the agent loads with get_skill(name) before the work each one
covers. index.md routes them, one "- load <name> when <situation>" line each; preamble() puts it
and the trust order (prompt.md) at the head of the system prompt. Only routed names are served."""

import re
from pathlib import Path

from starter.core.errors import NotFound

HERE = Path(__file__).parent
INDEX = HERE / "index.md"
ROUTE = re.compile(r"^- load ([a-z-]+) when .+$", re.MULTILINE)


def skill_names() -> list[str]:
    return ROUTE.findall(INDEX.read_text())


def get_skill(name: str) -> str:
    """Load a skill: the instructions for one kind of work, by its name in the skill index.

    Args:
        name: The skill's name as the index lists it, for example "escalation".
    """
    names = skill_names()
    if name not in names:
        raise NotFound(f"no skill {name!r}; the index routes {', '.join(names)}")
    return (HERE / f"{name}.md").read_text()


def preamble() -> str:
    """prompt.md with the index pasted in; the loop puts this before its own SYSTEM text."""
    template = (HERE / "prompt.md").read_text()
    return template.replace("{skill_index}", INDEX.read_text().strip()).strip()


def register_tools(gateway) -> None:
    gateway.register(get_skill, effect=False)
