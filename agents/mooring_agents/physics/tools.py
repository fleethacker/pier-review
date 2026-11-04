"""Tool catalog: each tool wraps exactly one modeling endpoint.

This is the only list of physics capabilities any agent may use. The Planner's LLM tool definitions are built
from it (input schemas come from contract/modeling.openapi.yaml). Served at GET /api/v1/tools.
"""

from typing import Literal

from pydantic import Field

from mooring.core.schemas import Model


class ToolSpec(Model):
    name: str
    description: str
    method: Literal["GET", "POST"]
    path: str = Field(description="Modeling path under /api/v1. {placeholders} are filled from the input.")
    request_schema: str | None = Field(description="Component name in contract/modeling.openapi.yaml.")
    async_job: bool = Field(default=False, description="True when the endpoint returns a job the gateway polls.")


TOOLS: list[ToolSpec] = [
    ToolSpec(name="get_scenario", description="Load the saved scenario: ship, berth, side, environment source, config.",
             method="GET", path="/scenarios/{scenario_id}", request_schema=None),
    ToolSpec(name="get_environment", description="Current wind, current and water level at the berth.",
             method="GET", path="/env/now", request_schema=None),
    ToolSpec(name="get_forecast", description="Forecast wind, current and water level at the berth.",
             method="GET", path="/env/forecast", request_schema=None),
    ToolSpec(name="get_ship", description="Ship class particulars, fittings and push points.",
             method="GET", path="/ships/{class_id}", request_schema=None),
    ToolSpec(name="get_berth", description="Berth geometry, pier fittings with capacities, fenders, depths.",
             method="GET", path="/berths/{berth_id}", request_schema=None),
    ToolSpec(name="compute_loads", description="Wind and current forces on the ship.",
             method="POST", path="/loads/environmental", request_schema="LoadsRequest"),
    ToolSpec(name="analyze_mooring", description="Line, fitting and fender loads plus NSTM 582 findings.",
             method="POST", path="/mooring/analyze", request_schema="AnalyzeRequest"),
    ToolSpec(name="limit_envelope", description="Wind speed that first overloads the plan, per direction.",
             method="POST", path="/mooring/envelope", request_schema="LimitEnvelopeRequest"),
    ToolSpec(name="risk_exceedance", description="Probability that gusts push any element past its limit.",
             method="POST", path="/risk/exceedance", request_schema="ExceedanceRequest", async_job=True),
    ToolSpec(name="recommend_config", description="Candidate line configurations scored at the MST design condition.",
             method="POST", path="/mooring/recommend", request_schema="RecommendRequest", async_job=True),
    ToolSpec(name="plan_tugs", description="Tug force, bollard pull and horsepower to land and hold the ship.",
             method="POST", path="/tugs/berthing-plan", request_schema="BerthingTugRequest"),
    ToolSpec(name="hold_tugs", description="Tugs needed to relieve overloaded lines on a moored ship.",
             method="POST", path="/tugs/hold-plan", request_schema="HoldTugRequest"),
    ToolSpec(name="berthing_windows", description="Times with low current and gusts for berthing.",
             method="POST", path="/windows/berthing", request_schema="BerthingWindowRequest"),
    ToolSpec(name="generate_sequence", description="Ordered line-handling steps for a configuration.",
             method="POST", path="/mooring/sequence", request_schema="SequenceRequest"),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
