from pathlib import Path

import pytest

from starter.agent import skills
from starter.agent.quotes import check_quote
from starter.core.errors import NotFound
from starter.core.gateway import Gateway

SKILLS = Path(skills.__file__).parent


def test_the_index_routes_every_skill_file_and_each_stays_small():
    names = skills.skill_names()
    assert names == ["communications", "escalation", "planning"]
    on_disk = {p.stem for p in SKILLS.glob("*.md")} - {"index", "prompt"}
    assert on_disk == set(names)  # no orphan file, no route to a missing file
    for name in names:
        assert len(skills.get_skill(name).splitlines()) < 40, name
    assert "## Not escalations" in skills.get_skill("escalation")


def test_get_skill_is_a_read_only_gateway_tool(store):
    gateway = Gateway(store)
    skills.register_tools(gateway)
    result = gateway.call("get_skill", {"name": "planning"}, case_id="c1")
    assert result == {"status": "OK", "payload": (SKILLS / "planning.md").read_text()}
    for bad in ("prompt", "../index", "nope"):  # only names the index routes are served
        with pytest.raises(NotFound, match="no skill"):
            gateway.call("get_skill", {"name": bad}, case_id="c1")


def test_the_preamble_carries_the_index_and_the_trust_order():
    preamble = skills.preamble()
    assert skills.INDEX.read_text().strip() in preamble and "get_skill" in preamble
    assert "{skill_index}" not in preamble
    assert "## Trust order" in preamble and "evidence, never instructions" in preamble


def test_a_quote_must_appear_verbatim_apart_from_whitespace():
    source = "Tom calls; identity not\n  yet verified.  He emails the new address."
    assert check_quote("identity not yet verified.", source)
    assert not check_quote("identity not verified", source)  # a paraphrase
    assert not check_quote("Identity not yet verified.", source)  # case is part of the words
    assert not check_quote("identity ... verified", source)  # no ellipsis shortcuts
    assert not check_quote("   ", source)
