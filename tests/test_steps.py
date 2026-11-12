from starter.eval.steps import cut_steps

INDEX = """# Case 900: Boiler out

Ana reports no heating.

## Outcome

FORBIDDEN_OUTCOME: engineer booked.
"""

HISTORY = """## History

- 1 Oct: Ana emails: the boiler shows F28.
- 1 Oct 09:30: Agent replies EXPECTED_NEXT_1 asking for a photo.
- 2 Oct: Ana sends the photo.
- 2 Oct: Agent books an engineer EXPECTED_NEXT_2.
  The slot is Friday morning.
- 3 Oct: Agent confirms the slot to Ana EXPECTED_NEXT_3.
- 4 Oct: Ana replies FUTURE_REPLY: thanks.
"""


def make_case(tmp_path):
    folder = tmp_path / "900"
    folder.mkdir()
    (folder / "index.md").write_text(INDEX)
    (folder / "history.md").write_text(HISTORY)
    return folder


def test_one_point_per_agent_action_and_no_future_ever_leaks(tmp_path):
    points = cut_steps(make_case(tmp_path))
    assert [p["step"] for p in points] == [1, 2, 3]
    for n, point in enumerate(points, start=1):
        assert point["case_id"] == "900"
        assert f"EXPECTED_NEXT_{n}" in point["target"]
        assert point["target"].startswith("Agent ")
        for later in range(n, 4):  # its own target and every later agent action stay hidden
            assert f"EXPECTED_NEXT_{later}" not in point["input"]
        for canary in ("FORBIDDEN_OUTCOME", "FUTURE_REPLY"):
            assert canary not in point["input"] and canary not in point["target"]
    assert "Ana reports no heating." in points[0]["input"]
    assert "the boiler shows F28" in points[0]["input"]
    assert "Ana sends the photo." in points[1]["input"]  # others' messages are inputs
    assert "The slot is Friday morning." in points[1]["target"]  # a continuation line stays
    assert "EXPECTED_NEXT_2" in points[2]["input"]  # earlier agent actions become inputs


def test_the_agent_name_is_a_parameter(tmp_path):
    assert cut_steps(make_case(tmp_path), agent="Ana")[0]["target"].startswith("Ana emails")
