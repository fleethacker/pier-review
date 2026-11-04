"""Types shared by every module: base model, status enums, provenance, findings, response envelope, jobs.

Conventions (see docs/PLAN.md, "API conventions"):
- Every numeric field name carries its unit suffix: _kt, _ft, _lbf, _ftlbf, _lt, _hp, _deg, _circ_in, _utc.
- Wind direction is where the wind blows FROM (meteorological). Current direction is where the water flows
  TOWARD (oceanographic set). Both in degrees true.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Base for all API models. Unknown fields are rejected so typos in UI payloads fail loudly."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())


Status = Literal["GREEN", "AMBER", "RED"]
Severity = Literal["INFO", "AMBER", "RED"]
SideTo = Literal["port", "starboard"]
MooringServiceType = Literal["I", "II", "IIA", "III"]


class Provenance(Model):
    """Where a value came from, so the UI and safety sheet can show how much to trust it."""

    source: str = Field(description="Human-readable source, e.g. 'NSTM 582 Table 582-5-6' or 'mock seed data'.")
    url: str | None = None
    confidence: Literal["published", "estimated", "mock", "vision"]
    notes: str | None = None


class Finding(Model):
    """One rule result from the NSTM 582 rule registry (see GET /rules)."""

    rule_id: str = Field(examples=["LINE-WLL"])
    severity: Severity
    element_ids: list[str] = Field(default_factory=list, examples=[["line-2"]])
    message: str
    reference: str = Field(description="NSTM 582 paragraph or table the rule implements.")


T = TypeVar("T")


class Envelope(Model, Generic[T]):
    """Wrapper returned by every compute endpoint so each number can be traced and reproduced."""

    result_id: str = Field(description="Stable id; the agent and safety sheet cite numbers by this id.")
    model: str = Field(description="Module that produced the result, e.g. 'mooring.solver.static'.")
    model_version: str
    backend: Literal["mock", "real"] = Field(description="'mock' until the workstream's real module lands.")
    inputs_hash: str = Field(description="sha256 of the canonical request JSON.")
    computed_at_utc: datetime
    status: Status
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[Finding] = Field(default_factory=list)
    result: T


# ---------- Async jobs ----------

JobState = Literal["queued", "running", "succeeded", "failed"]


class JobAccepted(Model):
    """Returned with HTTP 202 by every long-running endpoint."""

    job_id: str
    kind: str = Field(description="Endpoint family, e.g. 'risk.exceedance'.")
    status_url: str
    events_url: str = Field(description="Server-Sent Events stream of progress for this job.")


class JobStatus(Model):
    job_id: str
    kind: str
    state: JobState
    progress: float = Field(ge=0, le=1)
    created_at_utc: datetime
    finished_at_utc: datetime | None = None
    result: dict[str, Any] | None = Field(
        default=None, description="The module's response envelope once state is 'succeeded'."
    )
    error: str | None = None


class JobProgressEvent(Model):
    """SSE `progress` event on /jobs/{job_id}/events."""

    job_id: str
    progress: float
    message: str


class JobDoneEvent(Model):
    """SSE `done` event on /jobs/{job_id}/events. Fetch the result from status_url."""

    job_id: str
    state: JobState


class Health(Model):
    status: Literal["ok"]
    backend: Literal["mock", "real", "mixed"]


class VersionInfo(Model):
    api_version: str
    modules: dict[str, str] = Field(description="Module name -> 'mock' or the real module version.")
