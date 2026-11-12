"""The product agent: one case in, an AgentResult out. Claude drives the gateway's tools through
the SDK tool runner when ANTHROPIC_API_KEY is set; otherwise FakeProvider runs the same tools
deterministically, so everything works offline.

The trace is what reviewers read: every step is a dict with at least "tool", "status" (SIMULATED,
OK or ERROR) and "error" (None or the message). trace[0] is exactly what the model was given; one
"tool_call" step per tool call, failed ones included; the last step carries the final state."""

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from anthropic import beta_tool

from starter.agent import skills
from starter.core import tracing
from starter.core.errors import CaseCancelled
from starter.core.gateway import Gateway, current_case
from starter.runtime.config import MODEL_MAX_RETRIES, Settings

SYSTEM = (
    "You handle one case for the operations team. Read it, act through the tools, and finish "
    "with a short final answer saying what you did and why. Every tool call is simulated and "
    "logged; never claim an action you did not take through a tool. End the final answer with "
    "exactly one line: STATE: DONE (handled), STATE: NEEDS_INFO (you need more from someone "
    "before acting) or STATE: ESCALATED (a person must decide)."
)


def system_prompt() -> str:
    """The skills preamble (index and trust order), then the rules. Read on every run."""
    return f"{skills.preamble()}\n\n{SYSTEM}"


STATE_LINE = re.compile(r"^[ \t]*STATE:[ \t]*(DONE|NEEDS_INFO|ESCALATED)[ \t]*$", re.MULTILINE)


@dataclass
class AgentResult:
    final_answer: str
    final_state: str  # DONE | NEEDS_INFO | ESCALATED | ERROR
    reasoning: str
    actions: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    trace_id: str | None = None  # the OpenTelemetry trace this run's spans belong to
    spans: list[dict] = field(default_factory=list)  # redacted, see starter.core.tracing


def step(kind: str, tool: str | None = None, status: str = "OK", error: str | None = None, **rest):
    return {"type": kind, "tool": tool, "status": status, "error": error, **rest}


def parse_state(answer: str) -> tuple[str, str]:
    """(state, answer without the STATE line). No STATE line means ERROR: nothing is assumed."""
    states = STATE_LINE.findall(answer)
    if not states:
        return "ERROR", answer.strip()
    return states[-1], STATE_LINE.sub("", answer).strip()


def build_messages(case: dict) -> list[dict]:
    return [{"role": "user", "content": f"Case {case['id']}\n\n{case['body']}"}]


def gateway_tools(
    gateway: Gateway,
    case_id: str,
    actions: list[dict],
    trace: list[dict],
    cancel: threading.Event,
    seconds_left: Callable[[], float],
) -> list:
    """Each gateway tool as an SDK tool bound to this case. Arguments are checked by the gateway
    alone, so a bad call is traced as ERROR before the runner hands the error back to Claude.
    A call after the case is cancelled or out of time raises CaseCancelled and runs nothing."""

    def bind(name: str, fn):
        spec = beta_tool(fn)  # schema and description from the tool's type hints and docstring

        def call(**args):
            try:
                seconds_left()
                result = gateway.call(name, args, case_id, cancel)
            except Exception as exc:
                trace.append(step("tool_call", name, "ERROR", str(exc), args=args))
                raise
            trace.append(
                step("tool_call", name, result["status"], args=args, payload=result["payload"])
            )
            actions.append({"tool": name, "args": args, **result})
            return json.dumps(result)

        return beta_tool(
            call, name=name, description=spec.description, input_schema=spec.input_schema
        )

    return [bind(name, fn) for name, fn in gateway.tools.items()]


class FakeProvider:
    """Offline stand-in: calls send_message once, then answers. Named in every output."""

    name = "fake"

    def run(self, system, messages, tools, trace, seconds_left):
        # ponytail: always the example vertical's send_message; teach it your tools if the
        # offline demo needs a different first action.
        tool = next(t for t in tools if t.name == "send_message")
        tool.call({"to": "case-owner", "body": "We have your case and are working on it."})
        answer = (
            "FakeProvider (no ANTHROPIC_API_KEY): acknowledged the case with one message.\n"
            "STATE: DONE"
        )
        return answer, "FakeProvider is deterministic: one acknowledgement, then stop."


class ClaudeProvider:
    name = "claude"

    def __init__(self, settings: Settings):
        import anthropic

        self.model = settings.model
        self.model_timeout_s = settings.model_timeout_s
        self.max_iterations = settings.max_iterations
        self.effort = settings.effort
        self.client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.model_timeout_s,
            max_retries=MODEL_MAX_RETRIES,
        )

    def run(self, system, messages, tools, trace, seconds_left: Callable[[], float]):
        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=tools,
            max_iterations=self.max_iterations,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # a safety decline is retried on a fallback model, same call
        )

        def before_each_call() -> None:
            """Stop if the case is out of time; else cap this call, and its retry, to what is
            left. The SDK reads client.timeout per request; this client is this run's own."""
            # ponytail: checked before the runner executes the last reply's tool calls, so their
            # time is not counted here; the per-call timeout still bounds the overrun.
            tries = 1 + MODEL_MAX_RETRIES
            self.client.timeout = min(self.model_timeout_s, seconds_left() / tries)

        before_each_call()
        notes, last = [], None
        for message in runner:
            last = message
            content = [block.to_dict() for block in message.content]
            trace.append(step("model_output", stop_reason=message.stop_reason, content=content))
            notes += [b.thinking for b in message.content if b.type == "thinking" and b.thinking]
            if message.stop_reason in ("tool_use", "pause_turn"):  # another call follows
                before_each_call()
        reasoning = "\n\n".join(notes)
        if last is None:
            return "No response from the model.", reasoning
        if last.stop_reason == "refusal":
            category = last.stop_details.category if last.stop_details else None
            return f"The model declined this case (category: {category}).", reasoning
        return "".join(b.text for b in last.content if b.type == "text"), reasoning


def run(
    case: dict,
    gateway: Gateway,
    settings: Settings,
    provider=None,
    deadline: float | None = None,
    cancel: threading.Event | None = None,
) -> AgentResult:
    """Run one case. case = {"id": str, "body": str}, already stripped of its outcome.
    deadline is a time.monotonic() value (default: now + settings.case_timeout_s); setting
    `cancel` stops the case: its next tool call or model call raises CaseCancelled."""
    if provider is None:
        provider = ClaudeProvider(settings) if settings.anthropic_api_key else FakeProvider()
    deadline = deadline or time.monotonic() + settings.case_timeout_s
    cancel = cancel or threading.Event()

    def seconds_left() -> float:
        if cancel.is_set():
            raise CaseCancelled("case cancelled")
        if (left := deadline - time.monotonic()) <= 0:
            raise CaseCancelled("case budget exhausted")
        return left

    system = system_prompt()
    messages = build_messages(case)
    actions: list[dict] = []
    trace: list[dict] = []
    tools = gateway_tools(gateway, case["id"], actions, trace, cancel, seconds_left)
    token = current_case.set(case)
    try:
        with tracing.collect("case", case_id=case["id"]) as (trace_id, spans):
            trace.append(
                step(
                    "model_input",
                    provider=provider.name,
                    model=settings.model,
                    system=system,
                    messages=messages,
                    tools=[t.to_dict() for t in tools],
                    trace_id=trace_id,
                )
            )
            try:
                attributes = {"provider": provider.name, "model": settings.model}
                with tracing.tracer.start_as_current_span("model", attributes=attributes):
                    answer, reasoning = provider.run(system, messages, tools, trace, seconds_left)
                state, answer = parse_state(answer)
                error = (
                    None
                    if state != "ERROR"
                    else f"no STATE line in the final answer: {answer[:200]}"
                )
            except Exception as exc:  # the case still gets an answer and a trace saying what broke
                state, answer, reasoning, error = "ERROR", "", "", f"{type(exc).__name__}: {exc}"
            status = "ERROR" if state == "ERROR" else "OK"
            trace.append(
                step("final", status=status, error=error, final_state=state, trace_id=trace_id)
            )
    finally:
        current_case.reset(token)
    return AgentResult(answer, state, reasoning, actions, trace, trace_id, spans)
