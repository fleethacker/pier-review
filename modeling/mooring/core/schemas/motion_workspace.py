"""Motion-only authoring and session contracts; demonstrations never qualify a vessel."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Model, Validity
from .dynamics import ForcingSpec, ShipState, SimSessionCreated
from .environment import EnvironmentSnapshot
from .motion_controls import MotionControlsConfig
from .refdata import Berth, ShipClass, TugSpec


class MotionWaypoint(Model):
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed_kt: float = Field(ge=0, le=15)


class MotionRoute(Model):
    route_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    waypoints: list[MotionWaypoint] = Field(min_length=2, max_length=64)
    source: str = Field(min_length=1, max_length=1000)
    limitations: list[str] = Field(max_length=32)


class MotionWorkspaceSpec(Model):
    name: str = Field(min_length=1, max_length=120)
    ship_class_id: str
    loading: str = "full_load"
    berth_id: str = "NAVSTA-NORFOLK-P12-N"
    side_to: Literal["port", "starboard"] = "starboard"
    start: Literal["berth", "approach", "channel"] = "berth"
    initial_state: ShipState | None = None
    environment_mode: Literal["synthetic", "live", "snapshot"] = "synthetic"
    environment: EnvironmentSnapshot | None = None
    forcing: ForcingSpec | None = None
    controls: MotionControlsConfig | None = None
    tug_ids: list[str] | None = Field(default=None, max_length=8)
    duration_s: float = Field(default=3600, gt=0, le=14400)
    dt_s: float = Field(default=0.1, ge=0.05, le=0.5)
    initial_lines_attached: bool = False
    route_id: str | None = None
    route_follow: bool = False

    @model_validator(mode="after")
    def consistent_sources(self):
        if self.environment_mode == "live" and self.environment is not None:
            raise ValueError("live acquisition cannot also supply an environment snapshot")
        if self.environment_mode == "snapshot" and self.environment is None:
            raise ValueError("snapshot source requires its actual environment and provenance")
        if self.tug_ids is not None and len(set(self.tug_ids)) != len(self.tug_ids):
            raise ValueError("tug identifiers must be unique")
        if self.route_follow and not self.route_id:
            raise ValueError("route following requires an explicit demonstration route")
        if self.initial_lines_attached and self.start != "berth":
            raise ValueError("start with lines detached during channel/approach maneuvers")
        return self


class MotionWorkspaceScenario(Model):
    motion_scenario_id: str
    created_at_utc: AwareDatetime
    revision: str
    configuration: MotionWorkspaceSpec
    validity: Validity


class MotionWorkspacePreset(Model):
    preset_id: str
    title: str
    description: str
    configuration: MotionWorkspaceSpec
    validity: Validity


class MotionWorkspaceCatalog(Model):
    schema_version: Literal["motion-workspace-v1"] = "motion-workspace-v1"
    ships: list[ShipClass]
    berths: list[Berth]
    tugs: list[TugSpec]
    presets: list[MotionWorkspacePreset]
    routes: list[MotionRoute]
    telemetry_supported: bool = True


class MotionWorkspaceSessionRequest(Model):
    motion_scenario_id: str


class MotionWorkspaceSessionCreated(Model):
    session: SimSessionCreated
    scenario: MotionWorkspaceScenario
    ship: ShipClass
    berth: Berth
    controls: MotionControlsConfig
    route: MotionRoute | None
    environment: EnvironmentSnapshot
