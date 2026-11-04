"""Physics/Load agent schemas: tool calls through the gateway and the call ledger."""

from datetime import datetime
from typing import Any

from pydantic import Field

from mooring.core.schemas import Model, Status


class ToolInvocation(Model):
    input: dict[str, Any] = Field(default_factory=dict, description="Path params, query params or request body.")
    caller: str = Field(default="ui", description="Who is calling: 'ui', 'intake', 'planner', 'safety', ...")
    plan_id: str | None = Field(default=None, description="Ties the call to a plan for audit.")


class ToolCall(Model):
    """One ledger entry. Safety uses the ledger to prove every cited number came from a recorded tool call."""

    call_id: str
    at_utc: datetime
    caller: str
    plan_id: str | None
    tool: str
    request_hash: str
    result_id: str | None = Field(description="Envelope result_id when the tool returns one.")
    status: Status | None
    duration_ms: float
    error: str | None = None


class ToolCallResult(Model):
    call: ToolCall
    output: Any = Field(description="The modeling endpoint's response body, unchanged.")
