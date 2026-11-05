"""Physics/Load agent endpoints: tool catalog, logged tool gateway, call ledger."""

from fastapi import APIRouter

from mooring import refdata
from mooring.core import access

from ...physics.schemas import ToolCall, ToolCallResult, ToolInvocation
from ...physics.toolkit import PhysicsToolkit, UnknownTool, calls_for
from ...physics.tools import TOOLS, ToolSpec
from ..state import Client

router = APIRouter(tags=["Physics agent"])


@router.get("/tools", response_model=list[ToolSpec], summary="Physics tools agents may call")
def tools():
    return TOOLS


@router.post("/physics/tools/{tool_name}", response_model=ToolCallResult,
             summary="Run one physics tool through the logged gateway")
async def run_tool(tool_name: str, req: ToolInvocation, client: Client):
    if req.plan_id and not access.allowed("agent_plan", req.plan_id):
        raise refdata.NotFound(f"Plan '{req.plan_id}' not found")
    tk = PhysicsToolkit(client, req.caller, req.plan_id)
    try:
        output = await tk.call(tool_name, req.input)
    except UnknownTool as e:
        raise refdata.NotFound(str(e.args[0])) from None
    output = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
    return ToolCallResult(call=tk.last_call, output=output)


@router.get("/physics/calls", response_model=list[ToolCall], summary="Tool-call ledger, optionally for one plan")
def list_calls(plan_id: str | None = None):
    if plan_id and not (access.allowed("agent_plan", plan_id) or access.allowed("agent_report", plan_id)):
        raise refdata.NotFound(f"Plan '{plan_id}' not found")
    return calls_for(plan_id)

