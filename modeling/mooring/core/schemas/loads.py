"""Environmental load schemas (module M3, UFC 4-159-03 Chapter 4). Forces in the ship frame."""

from typing import Literal

from pydantic import Field

from .common import Envelope, Model, SideTo
from .environment import EnvironmentSnapshot


class LoadsRequest(Model):
    ship_class_id: str = Field(examples=["DDG-51-FIIA"])
    loading: str = "full_load"
    heading_true_deg: float = Field(ge=0, lt=360)
    water_depth_ft: float = Field(gt=0, description="Water depth at the ship; with draft it sets the current coefficient.")
    environment: EnvironmentSnapshot
    use_gust: bool = True
    shielding_factor: float = Field(default=1.0, ge=0, le=1, description="Reduction for pier buildings or ships upwind.")
    side_to: SideTo | None = Field(default=None, description="When given, off_pier_component_lbf is returned.")


class ForceSet(Model):
    """Forces and moment in the ship frame (+x forward, +y to port, yaw positive counterclockwise)."""

    fx_lbf: float
    fy_lbf: float
    mz_ftlbf: float


class ForceComponent(ForceSet):
    coefficients: dict[str, float] = Field(default_factory=dict)


class LoadsResult(Model):
    wind: ForceComponent
    current: ForceComponent
    total: ForceSet
    wind_rel_ship_deg: float
    current_rel_ship_deg: float
    off_pier_component_lbf: float | None = Field(
        default=None, description="Lateral force pushing the ship off the pier (negative = onto the pier)."
    )


class LoadsResponse(Envelope[LoadsResult]):
    pass


class PolarRequest(Model):
    ship_class_id: str
    loading: str = "full_load"
    water_depth_ft: float = Field(gt=0)
    wind_speed_kt: float = Field(ge=0)
    current_speed_kt: float = Field(default=0, ge=0)
    apply_to: Literal["wind", "current", "both"] = "both"
    step_deg: int = Field(default=5, ge=1, le=90)


class PolarPoint(ForceSet):
    rel_deg: float


class PolarResult(Model):
    points: list[PolarPoint]


class PolarResponse(Envelope[PolarResult]):
    pass
