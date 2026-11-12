"""HTTP doors to the gateway and the agent. Both need the admin token."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from starter.agent.cases import strip_outcome
from starter.agent.loop import run
from starter.runtime.deps import StoreDep, require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


class ToolCall(BaseModel):
    case_id: str
    args: dict = {}


class CaseIn(BaseModel):
    id: str
    body: str


@router.post("/tools/{name}")
def call_tool(name: str, call: ToolCall, request: Request) -> dict:
    return request.app.state.gateway.call(name, call.args, call.case_id)


@router.post("/runs")
def create_run(case: CaseIn, request: Request, store: StoreDep) -> dict:
    clean = {"id": case.id, "body": strip_outcome(case.body)}
    result = run(clean, request.app.state.gateway, request.app.state.settings)
    record = {"case_id": case.id, **asdict(result)}
    store.mutate(lambda data: data.setdefault("runs", []).append(record))
    return record
