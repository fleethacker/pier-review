"""Types shared by every module: base model, status enums, provenance, findings, response envelope, jobs.

Conventions (see docs/PLAN.md, "API conventions"):
- Every numeric field name carries its unit suffix: _kt, _ft, _lbf, _ftlbf, _lt, _hp, _deg, _circ_in, _utc.
- Wind direction is where the wind blows FROM (meteorological). Current direction is where the water flows
  TOWARD (oceanographic set). Both in degrees true.
"""

from datetime import datetime
from typing import Any, ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class Model(BaseModel):
    """Base for all API models. Unknown fields and NaN/Infinity are rejected so bad payloads fail loudly.

    NaN and infinity are never valid values: an unknown quantity is `null`, not 0, infinity or NaN.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=(), allow_inf_nan=False)

    # Only newly introduced, inactive fields are omitted. Do not globally exclude
    # None/defaults: legacy wire payloads and typed request hashes include them.
    wire_omitted_defaults: ClassVar[dict[str, Any]] = {}

    @model_serializer(mode="wrap")
    def _compatible_wire(self, handler):
        data = handler(self)
        for name, default in self.wire_omitted_defaults.items():
            if name in data and data[name] == default:
                del data[name]
        return data


Status = Literal["GREEN", "AMBER", "RED"]
Severity = Literal["INFO", "AMBER", "RED"]
SideTo = Literal["port", "starboard"]
MooringServiceType = Literal["I", "II", "IIA", "III"]


# ---------- Validity, diagnostics and result manifest (S00a) ----------

ValidityState = Literal["valid", "limited", "invalid", "unknown"]


class ValidityReason(Model):
    """Why a result is limited or invalid. Codes are stable UPPER_SNAKE identifiers that clients may switch on."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", examples=["MISSING_FITTING_RATING"])
    message: str
    affected_components: list[str] = Field(
        default_factory=list, description="Element ids the reason applies to, e.g. 'line-2', 'P12N-B16'.", examples=[["line-2"]]
    )


class SolverResidual(Model):
    """One dimensional residual (e.g. net surge force) with the tolerance it was judged against."""

    name: str = Field(examples=["surge_force"])
    value: float
    unit: str = Field(examples=["lbf", "ftlbf"])
    tolerance: float = Field(gt=0, description="Same unit as value.")

    @property
    def within_tolerance(self) -> bool:
        return abs(self.value) <= self.tolerance


class SolverDiagnostics(Model):
    """Numerical evidence behind a result. Absent values are `null` (not measured), never 0 or NaN."""

    converged: bool | None = Field(default=None, description="Null when no iterative solve was performed.")
    iterations: int | None = Field(default=None, ge=0)
    residuals: list[SolverResidual] = Field(
        default_factory=list, description="Independent force and moment balances, each in its own unit."
    )
    active_constraints: list[str] = Field(
        default_factory=list, description="Contacts, slack lines and limits that were active at the solution."
    )
    rank: int | None = Field(default=None, ge=0, description="Numerical rank of the support (stiffness) matrix.")
    degrees_of_freedom: int | None = Field(default=None, ge=0, description="Rank is full when rank equals this.")
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rank_within_dof(self):
        if self.rank is not None and self.degrees_of_freedom is not None and self.rank > self.degrees_of_freedom:
            raise ValueError("rank cannot exceed degrees_of_freedom")
        return self


class Validity(Model):
    """Whether the numbers can be relied on, independent of the GREEN/AMBER/RED status.

    `valid`: inside the model's qualified domain. `limited`: usable with the stated caveats, so never an
    unconditional GREEN. `invalid`: do not use the numbers; status is RED. `unknown`: not assessed.
    A numerical failure is not proof that no physical solution exists: report it as `invalid` with a reason.
    """

    state: ValidityState
    reasons: list[ValidityReason] = Field(default_factory=list)
    diagnostics: SolverDiagnostics | None = None

    @model_validator(mode="after")
    def _reasons_required(self):
        if self.state in ("limited", "invalid") and not self.reasons:
            raise ValueError(f"validity '{self.state}' needs at least one reason")
        return self


class ManifestRecord(Model):
    """A resolved reference record that went into a result."""

    kind: str = Field(examples=["ship", "berth", "line_spec", "tug"])
    id: str
    revision: str | None = Field(default=None, description="Content hash or version of the record; null if unversioned.")


class ResultManifest(Model):
    """What a result depended on, so it can be reproduced. `inputs_hash` still hashes the request as sent;
    `resolved_inputs_hash` hashes the request after defaults and references are resolved."""

    resolved_inputs_hash: str | None = Field(default=None, description="sha256 of the canonical resolved inputs.")
    code_version: str | None = None
    records: list[ManifestRecord] = Field(default_factory=list)
    environment_hash: str | None = Field(default=None, description="sha256 of the environment snapshot used.")
    numerical_settings: dict[str, float | int | str | bool] = Field(default_factory=dict)
    rng_seed: int | None = None
    rng_model_revision: str | None = None


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

    wire_omitted_defaults = {"validity": None, "manifest": None}

    result_id: str = Field(description="Stable id; the agent and safety sheet cite numbers by this id.")
    model: str = Field(description="Module that produced the result, e.g. 'mooring.solver.static'.")
    model_version: str
    backend: Literal["mock", "real"] = Field(description="'mock' until the workstream's real module lands.")
    inputs_hash: str = Field(description="sha256 of the canonical request JSON.")
    computed_at_utc: datetime
    status: Status
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[Finding] = Field(default_factory=list)
    validity: Validity | None = Field(
        default=None,
        description="Omitted when unset; absence means UNKNOWN, never valid. New real paths always populate it. "
        "'invalid' requires status RED; 'limited' cannot be GREEN.",
    )
    manifest: ResultManifest | None = Field(default=None, description="Dependencies for reproducing the result; omitted when unset to preserve legacy response shapes.")
    result: T

    @model_validator(mode="after")
    def _status_agrees_with_validity(self):
        if self.validity is None:
            return self
        if self.validity.state == "invalid" and self.status != "RED":
            raise ValueError("an invalid result must have status RED")
        if self.validity.state == "limited" and self.status == "GREEN":
            raise ValueError("a limited result cannot have status GREEN")
        return self


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
