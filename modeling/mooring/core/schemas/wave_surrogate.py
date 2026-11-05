"""S4: seeded synthetic wave-forcing surrogate (visualization only).

Input is a labeled spectrum: EITHER one total sea state OR provider partitions (swell / wind sea), never both as additive
sources. Missing waves are `unavailable`, never zero; an explicit zero-height input is zero.
"""

from typing import Literal

from pydantic import Field, model_validator

from .common import Model

SYNTHETIC_LABEL = "SYNTHETIC / UNQUALIFIED: seeded random-phase JONSWAP-shaped surface elevation for visualization only. Not a forecast, not a measurement, and not berth forcing (offshore availability is not berth forcing)."

PartitionLabel = Literal["swell", "wind_sea"]


class WaveSpectrumComponent(Model):
    label: Literal["total_sea", "swell", "wind_sea"]
    hs_ft: float = Field(ge=0, description="Significant wave height (4 sqrt(m0)) of this component.")
    peak_period_s: float = Field(gt=0, description="Spectral peak period.")
    from_true_deg: float | None = Field(default=None, ge=0, lt=360, description="Provenance only; the surrogate is a scalar elevation at one point and does not model direction.")
    gamma: float = Field(default=3.3, ge=1.0, le=10.0, description="JONSWAP peak enhancement. A scenario shape parameter, not fitted to data.")


class WaveSpectrumInput(Model):
    kind: Literal["total", "partitions"]
    components: list[WaveSpectrumComponent] = Field(min_length=1)
    reported_total_hs_ft: float | None = Field(default=None, ge=0, description="Provider's reported total Hs alongside partitions. Checked for consistency, never added.")
    source: str = Field(min_length=1, description="Where these labeled parameters came from (e.g. a D4 record id or 'hand-entered scenario').")

    @model_validator(mode="after")
    def _no_double_count(self):
        labels = [c.label for c in self.components]
        if self.kind == "total":
            if labels != ["total_sea"]:
                raise ValueError("kind 'total' takes exactly one 'total_sea' component; a total plus partitions would double count")
            if self.reported_total_hs_ft is not None:
                raise ValueError("reported_total_hs_ft is only meaningful with partitions")
        else:
            if "total_sea" in labels:
                raise ValueError("kind 'partitions' cannot include a 'total_sea' component (double counting)")
            if len(set(labels)) != len(labels):
                raise ValueError("duplicate partition labels")
        return self


class WaveSurrogateRequest(Model):
    seed: int = Field(ge=0)
    duration_s: float = Field(default=600.0, gt=0, le=3600.0)
    dt_s: float = Field(default=0.5, gt=0, le=10.0)
    spectrum: WaveSpectrumInput | None = Field(default=None, description="None means waves are unavailable (not zero).")


class WaveSurrogateSeries(Model):
    t_s: list[float]
    elevation_ft: list[float] = Field(description="Sum of the component elevations; each partition added once.")
    components: dict[str, list[float]] = Field(default_factory=dict)


class WaveSurrogateResult(Model):
    state: Literal["synthetic", "unavailable"]
    label: str = SYNTHETIC_LABEL
    qualified: Literal[False] = False
    seed: int
    reasons: list[str] = Field(default_factory=list)
    series: WaveSurrogateSeries | None = None
    target_hs_ft: float | None = Field(default=None, description="sqrt(sum of component Hs^2): energy-additive, each source once.")
    realized_hs_ft: float | None = Field(default=None, description="4 x standard deviation of the generated series.")
    mean_zero_crossing_period_s: float | None = None
    source: str | None = None
    notes: list[str] = Field(default_factory=list)
