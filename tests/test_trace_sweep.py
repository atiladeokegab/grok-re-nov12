import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import trace_sweep  # noqa: E402


def missing_body(case: str) -> dict:
    """A real pydantic message: input_value differs per case, the bug does not."""
    return {
        "type": "tool_call",
        "tool": "send_message",
        "status": "ERROR",
        "error": "1 validation error for send_message\nbody\n  Missing required argument "
        f"[type=missing_argument, input_value=ArgsKwargs((), {{'to': '{case}'}}), "
        "input_type=ArgsKwargs]\n    For further information visit "
        "https://errors.pydantic.dev/2.14/v/missing_argument",
    }


OK = {"type": "tool_call", "tool": "get_skill", "status": "OK", "error": None}
FINAL = {"type": "final", "tool": None, "status": "ERROR", "error": "no STATE line"}


def write_traces(answers: Path, traces: dict[str, list[dict]]) -> Path:
    for case_id, steps in traces.items():
        (answers / case_id).mkdir(parents=True)
        lines = "".join(json.dumps(s) + "\n" for s in steps)
        (answers / case_id / "trace.jsonl").write_text(lines)
    return answers


def test_an_error_in_three_cases_is_a_system_bug(tmp_path, capsys):
    answers = write_traces(
        tmp_path / "ANSWERS",
        {c: [OK, missing_body(c), FINAL] for c in ("001", "002", "003")} | {"004": [OK, FINAL]},
    )
    assert trace_sweep.main([str(answers)]) == 1
    out = capsys.readouterr().out
    [row] = [line for line in out.splitlines() if "send_message" in line]
    assert row.split()[:2] == ["3", "3"]  # 3 cases, 3 calls: one row despite differing input
    assert "Missing required argument" in row and "input_value" not in row
    assert "get_skill" not in out and "no STATE line" not in out  # OK calls, final steps


def test_repeats_inside_two_cases_stay_below_the_bar(tmp_path, capsys):
    answers = write_traces(
        tmp_path / "ANSWERS", {c: [missing_body(c), missing_body(c)] for c in ("001", "002")}
    )
    assert trace_sweep.main([str(answers)]) == 0
    [row] = [line for line in capsys.readouterr().out.splitlines() if "send_message" in line]
    assert row.split()[:2] == ["2", "4"]


def test_no_traces_is_a_failure_not_a_clean_sweep(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert trace_sweep.main([str(tmp_path / "empty")]) == 2
    assert "no trace.jsonl" in capsys.readouterr().out
