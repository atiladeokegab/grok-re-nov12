"""The loop routes to skills: the skills preamble (index and trust order) leads the system
prompt, the loop's own rules follow, and get_skill is one of the agent's tools."""

from starter.agent import skills
from starter.agent.loop import SYSTEM, run, system_prompt
from starter.core.gateway import build_gateway
from starter.runtime.config import Settings

CASE = {"id": "s-1", "body": "A customer wants their money back."}


def test_system_prompt_is_the_skills_preamble_then_the_rules():
    assert system_prompt() == f"{skills.preamble()}\n\n{SYSTEM}"
    assert skills.INDEX.read_text().strip() in system_prompt()
    assert "get_skill" in system_prompt() and "STATE: NEEDS_INFO" in system_prompt()


def test_the_model_gets_the_prompt_and_the_get_skill_tool(store):
    first = run(CASE, build_gateway(store), Settings()).trace[0]
    assert first["system"] == system_prompt()
    assert "get_skill" in {t["name"] for t in first["tools"]}


def test_get_skill_is_registered_read_only(store):
    assert build_gateway(store).effects["get_skill"] is False
