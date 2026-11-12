import pytest

from starter.eval.holdout import HoldoutError, is_holdout, tuning_cases


def test_holdout_is_one_in_five_by_hash():
    assert [c for c in (f"{i:03d}" for i in range(1, 21)) if is_holdout(c)] == ["004", "011", "017"]


def test_tuning_refuses_holdout_ids():
    assert tuning_cases(["001", "002"]) == ["001", "002"]
    with pytest.raises(HoldoutError, match="004"):
        tuning_cases(["001", "004"])
