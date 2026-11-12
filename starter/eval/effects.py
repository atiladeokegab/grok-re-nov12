"""Side effects counted from the gateway's audit, not from what the agent says it did. An effect is
a tool_call event of an effect tool (live or simulated); a repeat the gateway answered from an
idempotent tool's first result did nothing and is not counted."""

import re
from collections import Counter

WORDS = "one two three four five six seven eight nine ten".split()
NUMBERS = {word: n for n, word in enumerate(WORDS, 1)}


def count_effects(events: list[dict], case_id: str, effects: dict[str, bool]) -> Counter:
    """{tool: effects recorded} for one case. `effects` is Gateway.effects: name -> is an effect."""
    return Counter(
        e["tool"]
        for e in events
        if e.get("type") == "tool_call"
        and e.get("case_id") == case_id
        and effects.get(e["tool"])
        and not e.get("repeat")
    )


def effects_line(counts: Counter) -> str:
    detail = ", ".join(f"{tool}: {n}" for tool, n in sorted(counts.items()))
    return f"Effects: {counts.total()}" + (f" ({detail})" if detail else "")


def claim_mismatches(answer: str, counts: Counter, effects: dict[str, bool]) -> list[str]:
    """Each "<number> <noun>" in the answer whose noun names an effect tool and whose number is not
    what the gateway recorded for that tool."""
    # shortcut: the noun is the tool name's last word (send_email -> "2 emails"); a claim worded
    # any other way is not checked. Add nouns per tool if the event's tools read differently.
    found = []
    for tool in sorted(t for t, is_effect in effects.items() if is_effect):
        noun = re.escape(tool.rsplit("_", 1)[-1])
        claim = re.compile(rf"\b(\d+|{'|'.join(NUMBERS)})\s+{noun}s?\b", re.IGNORECASE)
        for match in claim.finditer(answer):
            word = match.group(1).lower()
            n = int(word) if word.isdigit() else NUMBERS[word]
            if n != counts[tool]:
                found.append(f"the answer claims {n} {tool}, the gateway recorded {counts[tool]}")
    return found
