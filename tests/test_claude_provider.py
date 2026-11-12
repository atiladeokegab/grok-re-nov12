"""The real provider, run offline: the SDK tool runner talks to a mock transport that plays
Claude's side (one tool_use, then a final answer), so the gateway wiring is proven without a key."""

import json

import anthropic
import httpx2

from starter.agent.loop import ClaudeProvider, run, system_prompt
from starter.core.gateway import build_gateway
from starter.runtime.config import Settings


def reply(content, stop_reason):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def mock_claude(tool_input: dict, final_text: str) -> tuple[ClaudeProvider, list[dict]]:
    """A ClaudeProvider whose API replies with one send_message call, then final_text."""
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            use = {"type": "tool_use", "id": "tu_1", "name": "send_message", "input": tool_input}
            return httpx2.Response(200, json=reply([use], "tool_use"))
        return httpx2.Response(200, json=reply([{"type": "text", "text": final_text}], "end_turn"))

    provider = ClaudeProvider(Settings(anthropic_api_key="test-key"))
    provider.client = anthropic.Anthropic(
        api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    return provider, requests


def test_claude_provider_drives_gateway_tools(store):
    provider, requests = mock_claude({"to": "ann", "body": "on it"}, "Done.\nSTATE: DONE")
    settings = Settings(anthropic_api_key="test-key")
    result = run({"id": "c9", "body": "Help."}, build_gateway(store), settings, provider)

    assert (result.final_answer, result.final_state) == ("Done.", "DONE")
    assert [(a["tool"], a["status"]) for a in result.actions] == [("send_message", "SIMULATED")]
    assert requests[0]["model"] == "claude-opus-5-5"
    assert {"send_message", "get_skill"} <= {t["name"] for t in requests[0]["tools"]}
    assert requests[0]["system"] == system_prompt()
    tool_result = requests[1]["messages"][-1]["content"][0]
    assert json.loads(tool_result["content"])["status"] == "SIMULATED"


def test_failing_tool_call_is_traced_as_error_and_returned_to_claude(store):
    provider, requests = mock_claude({"to": "ann"}, "Could not send it.\nSTATE: NEEDS_INFO")
    settings = Settings(anthropic_api_key="test-key")
    result = run({"id": "c9", "body": "Help."}, build_gateway(store), settings, provider)

    [failed] = [s for s in result.trace if s["type"] == "tool_call"]
    assert (failed["tool"], failed["status"]) == ("send_message", "ERROR")
    assert "body" in failed["error"] and "Missing required argument" in failed["error"]
    assert result.actions == [] and result.final_state == "NEEDS_INFO"
    assert requests[1]["messages"][-1]["content"][0]["is_error"] is True
