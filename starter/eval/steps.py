"""Per-step test points. A case history is a list of events, one "- <when>: <text>" line each (an
indented line continues the event above). Every event the agent itself wrote is a test point: its
input is the case plus every event before it, its target is the event. Other people's messages
are inputs only: the model cannot be asked to predict someone else's reply."""

from pathlib import Path

from starter.agent.cases import strip_outcome


def event_text(event: str) -> str:
    return event[2:].split(": ", 1)[-1]  # drop "- " and the "<when>: " prefix


def cut_steps(folder: Path, agent: str = "Agent") -> list[dict]:
    """[{"case_id", "step", "input", "target"}], one per agent event, in history order."""
    # ponytail: the actor is the first word after the date; change event_text for the event's
    # real history format (sender headers, channels) when it differs.
    index = strip_outcome((folder / "index.md").read_text())
    history = folder / "history.md"
    lines = strip_outcome(history.read_text()).splitlines() if history.exists() else []
    head: list[str] = []  # lines before the first event, e.g. "## History"
    events: list[str] = []
    for line in lines:
        if line.startswith("- "):
            events.append(line)
        elif events:
            events[-1] += "\n" + line
        else:
            head.append(line)
    points = []
    for n, event in enumerate(events):
        text = event_text(event)
        if text == agent or text.startswith(agent + " "):
            prefix = "\n".join(head + events[:n]).strip()
            points.append(
                {
                    "case_id": folder.name,
                    "step": len(points) + 1,
                    "input": f"{index}\n\n{prefix}".strip(),
                    "target": text,
                }
            )
    return points
