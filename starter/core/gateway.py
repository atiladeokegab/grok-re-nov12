"""The one tool door. Every tool the agent or an API caller uses goes through Gateway.call:
arguments are validated against the tool's type hints and the call is written to the event log.

A tool with an external effect (effect=True, the default) only runs when the gateway is live
(EFFECTS=live). Otherwise its function is never called: the gateway checks the arguments and
returns {"status": "SIMULATED", "payload": <the checked arguments, or simulate(**arguments)>}.
A read-only tool (effect=False) always runs and returns {"status": "OK", ...}, as does an effect
tool on a live gateway.

An effect tool registered with idempotent=True runs once per (case, tool, checked arguments): a
repeat within the case returns the first result unchanged, runs and simulates nothing, and is
audited as a tool_call event with "repeat": True. The key is derived, not passed, so a model that
retries a send cannot send twice; register without it a tool whose repeats are meant (two
reminders). Only a call that returned is remembered: one that raised can be retried. A live effect
that ran is never reported as failed: if the case is cancelled while it runs, the gateway still
audits it and returns its result.

latency=(low, high) waits a random low to high seconds before each simulated effect, so a recorded
demo grows at a believable pace; only scripts/demo/record.py sets it (DEMO_LATENCY)."""

import contextlib
import inspect
import json
import random
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from pydantic import validate_call

from starter.core.errors import CaseCancelled, NotFound
from starter.core.store import Store
from starter.core.tracing import tracer

# The case being run (the runner's case dict); the agent loop sets it, so a simulate= hook can
# check a call against the case without it being a tool argument.
current_case: ContextVar[dict | None] = ContextVar("current_case", default=None)


class Gateway:
    def __init__(
        self,
        store: Store,
        effects: str = "simulate",
        latency: tuple[float, float] | None = None,
    ):
        self.store = store
        self.live = effects == "live"
        self.latency = latency
        self.tools: dict[str, Callable[..., Any]] = {}  # name -> argument-checking wrapper
        self.effects: dict[str, bool] = {}
        self.simulators: dict[str, Callable[..., Any]] = {}  # effect tools only
        self.checks: dict[str, Callable[..., dict]] = {}  # name -> checked arguments, runs nothing
        self.idempotent: dict[str, bool] = {}
        # shortcut: remembered in this process only, one lock for every idempotent call; move to
        # the store with a reservation if several instances serve the same cases.
        self.done: dict[tuple, dict] = {}  # (case_id, tool, canonical arguments) -> first result
        self._once = threading.Lock()

    def register(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        effect: bool = True,
        simulate: Callable[..., Any] | None = None,
        idempotent: bool = False,
    ):
        """Decorator. Type hints are the argument schema, the docstring is the description.
        simulate(**checked_arguments), if given, is the payload an effect tool returns when the
        gateway is not live; without it the payload is the checked arguments. idempotent=True: a
        repeat call in the same case returns the first result (see the module docstring)."""

        def add(fn: Callable[..., Any]) -> Callable[..., Any]:
            name = fn.__name__
            if name in self.tools:
                raise ValueError(f"tool {name!r} is already registered")
            self.tools[name] = validate_call(fn)
            self.effects[name] = effect
            self.idempotent[name] = idempotent
            check = self.checks[name] = validate_call(_arguments_of(fn))
            if effect:
                self.simulators[name] = lambda **args: (simulate or dict)(**check(**args))
            return fn

        return add(fn) if fn else add

    def call(
        self, name: str, args: dict, case_id: str, cancel: threading.Event | None = None
    ) -> dict:
        """Validate, run (or simulate), audit. Bad arguments raise ValueError (HTTP 422). Once
        `cancel` is set, the call raises CaseCancelled: nothing runs and nothing is written."""
        if name not in self.tools:
            raise NotFound(f"no tool {name!r}")
        if cancel is not None and cancel.is_set():
            raise CaseCancelled("case cancelled")
        key = None
        if self.idempotent[name]:
            key = (
                case_id,
                name,
                json.dumps(self.checks[name](**args), sort_keys=True, default=str),
            )
        with self._once if key else contextlib.nullcontext():
            if key in self.done:
                result = self.done[key]
                event = {"case_id": case_id, "tool": name, "args": args, "result": result}
                self.store.publish({"type": "tool_call", **event, "repeat": True})
                return result
            result = self._run(name, args, case_id, cancel)
            if key:
                self.done[key] = result
        self.store.publish(
            {"type": "tool_call", "case_id": case_id, "tool": name, "args": args, "result": result}
        )
        return result

    def _run(self, name: str, args: dict, case_id: str, cancel: threading.Event | None) -> dict:
        simulated = self.effects[name] and not self.live
        run = self.simulators[name] if simulated else self.tools[name]
        attributes = {"tool": name, "case_id": case_id, "simulated": simulated}
        attributes |= {f"arg.{k}": str(v) for k, v in args.items()}  # redacted on export
        with tracer.start_as_current_span("gateway.call", attributes=attributes):
            if simulated and self.latency:
                time.sleep(random.uniform(*self.latency))
            payload = run(**args)  # pydantic.ValidationError is a ValueError
        if cancel is not None and cancel.is_set() and not (self.effects[name] and self.live):
            raise CaseCancelled("case cancelled")  # cancelled while it ran, no effect: no audit
        return {"status": "SIMULATED" if simulated else "OK", "payload": payload}


def _arguments_of(fn: Callable[..., Any]) -> Callable[..., dict]:
    """A stand-in with fn's signature that returns its checked arguments and does nothing else."""

    def arguments(**kwargs) -> dict:
        return kwargs

    arguments.__signature__ = inspect.signature(fn).replace(return_annotation=dict)
    arguments.__annotations__ = {**inspect.get_annotations(fn), "return": dict}
    arguments.__name__, arguments.__qualname__ = fn.__name__, fn.__qualname__
    return arguments


def build_gateway(
    store: Store, effects: str = "simulate", latency: tuple[float, float] | None = None
) -> Gateway:
    """A gateway with every vertical's tools and get_skill registered."""
    from starter import verticals
    from starter.agent import skills

    gateway = Gateway(store, effects, latency)
    for module in verticals.modules():
        if hasattr(module, "register_tools"):
            module.register_tools(gateway)
    skills.register_tools(gateway)  # get_skill: the system prompt's index names what it loads
    return gateway
