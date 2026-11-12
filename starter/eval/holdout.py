"""The holdout split. One case in five, chosen by hash so it never moves, is never tuned on:
prompt tweaks, few-shot picks and threshold sweeps go through tuning_cases(), which refuses it."""

import hashlib
from collections.abc import Iterable


class HoldoutError(ValueError):
    pass


def is_holdout(case_id: str) -> bool:
    return int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 5 == 0


def tuning_cases(case_ids: Iterable[str]) -> list[str]:
    """Return the ids unchanged, or raise if any is a holdout case."""
    ids = list(case_ids)
    held = [c for c in ids if is_holdout(c)]
    if held:
        raise HoldoutError(f"holdout cases may not be used for tuning: {', '.join(held)}")
    return ids
