"""Mock environment service (M1): a deterministic synthetic tide, current and wind for any time.

The real module replaces this with NOAA CO-OPS (8638614 wind, cb0402 current, 8638610 water level), CBOFS and
NWS forecasts. Same function signatures.
"""

import math
from datetime import UTC, datetime, timedelta

from mooring import refdata
from mooring.core.schemas import (
    Distribution,
    EnvironmentSnapshot,
    EnvScenario,
    EnvScenarioCreate,
    FitWindow,
    ForecastSeries,
    GustModel,
    GustSector,
    HistorySeries,
    Provenance,
    StationQuality,
)

from mooring.core.store import DocStore
from mooring.core.envelopes import new_id, utcnow

TIDE_PERIOD_H = 12.42
FLOOD_SET_DEG = 190.0  # cb0402 mean flood direction
EBB_SET_DEG = 10.0

_scenarios = DocStore("env_scenario", EnvScenario)


def _hours(t: datetime) -> float:
    return t.timestamp() / 3600.0


def synthetic(t: datetime, source: str = "mock", stations: tuple[str, str, str] = ("8638614", "cb0402", "8638610")):
    h = _hours(t)
    phase = 2 * math.pi * h / TIDE_PERIOD_H
    water_level = 1.4 + 1.3 * math.sin(phase)
    flow = 0.9 * math.cos(phase)  # + flood, - ebb
    speed = abs(flow)
    wind = 12 + 4 * math.sin(2 * math.pi * h / 24 + 1.0) + 2 * math.sin(2 * math.pi * h / 3.3)
    wind_dir = (215 + 25 * math.sin(2 * math.pi * h / 30)) % 360
    stage = "slack" if speed < 0.15 else ("flood" if flow > 0 else "ebb")
    return EnvironmentSnapshot(
        valid_at_utc=t,
        source=source,
        wind_speed_kt=round(max(wind, 0), 1),
        wind_gust_kt=round(max(wind, 0) * 1.35, 1),
        wind_from_true_deg=round(wind_dir, 1),
        current_speed_kt=round(speed, 2),
        current_set_true_deg=FLOOD_SET_DEG if flow > 0 else EBB_SET_DEG,
        water_level_mllw_ft=round(water_level, 2),
        tide_stage=stage,
        quality=[StationQuality(station_id=s, age_s=0, flags=["mock"]) for s in stations],
    )


def with_relative(snap: EnvironmentSnapshot, heading_true_deg: float | None) -> EnvironmentSnapshot:
    if heading_true_deg is None:
        return snap
    return snap.model_copy(
        update={
            "wind_rel_ship_deg": round((snap.wind_from_true_deg - heading_true_deg) % 360, 1),
            "current_rel_ship_deg": round((snap.current_set_true_deg - heading_true_deg) % 360, 1),
        }
    )


def _stations(berth_id: str) -> tuple[str, str, str]:
    s = refdata.berth(berth_id).env_station_ids
    return (s.wind, s.current, s.water_level)


def now(berth_id: str, heading_true_deg: float | None = None, env_scenario_id: str | None = None) -> EnvironmentSnapshot:
    if env_scenario_id:
        return with_relative(scenario_snapshot(env_scenario_id, utcnow()), heading_true_deg)
    t = utcnow().replace(second=0, microsecond=0)
    return with_relative(synthetic(t, "mock", _stations(berth_id)), heading_true_deg)


def forecast(berth_id: str, hours: int = 48, step_min: int = 30) -> ForecastSeries:
    from mooring.data_simulation.legacy_forecast import generate
    return generate(berth_id, utcnow(), hours, step_min, _stations(berth_id), synthetic)


def history(station_id: str, start: datetime, end: datetime, step_min: int = 6) -> HistorySeries:
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    n = min(int((end - start).total_seconds() / 60 / step_min) + 1, 5000)
    series = [synthetic(start + timedelta(minutes=i * step_min), "replay") for i in range(max(n, 0))]
    return HistorySeries(station_id=station_id, start_utc=start, end_utc=end, series=series)


def create_scenario(req: EnvScenarioCreate) -> EnvScenario:
    sc = EnvScenario(**req.model_dump(), env_scenario_id=new_id("envsc"), created_at_utc=utcnow())
    _scenarios[sc.env_scenario_id] = sc
    return sc


def get_scenario(env_scenario_id: str) -> EnvScenario:
    if env_scenario_id not in _scenarios:
        raise refdata.NotFound(f"Environment scenario '{env_scenario_id}' not found")
    return _scenarios[env_scenario_id]


def scenario_snapshot(env_scenario_id: str, t: datetime) -> EnvironmentSnapshot:
    sc = get_scenario(env_scenario_id)
    if sc.kind == "replay" and sc.replay_start_utc:
        elapsed = t - sc.created_at_utc
        return synthetic(sc.replay_start_utc + elapsed, "replay")
    wind = sc.wind_speed_kt
    if sc.kind == "ramp" and sc.ramp_to_wind_kt is not None and sc.ramp_minutes:
        frac = min(1.0, (t - sc.created_at_utc).total_seconds() / 60 / sc.ramp_minutes)
        wind = sc.wind_speed_kt + frac * (sc.ramp_to_wind_kt - sc.wind_speed_kt)
    gust = sc.wind_gust_kt if sc.wind_gust_kt is not None else wind
    if sc.kind == "ramp" and sc.wind_gust_kt is not None and sc.wind_speed_kt > 0:
        gust = wind * sc.wind_gust_kt / sc.wind_speed_kt
    return EnvironmentSnapshot(
        valid_at_utc=t,
        source="scenario",
        wind_speed_kt=round(wind, 1),
        wind_gust_kt=round(max(gust, wind), 1),
        wind_from_true_deg=sc.wind_from_true_deg,
        current_speed_kt=sc.current_speed_kt,
        current_set_true_deg=sc.current_set_true_deg,
        water_level_mllw_ft=sc.water_level_mllw_ft,
        quality=[StationQuality(station_id=sc.env_scenario_id, age_s=0, flags=["scenario"])],
    )


def gust_model(station_id: str) -> GustModel:
    sectors = []
    for i in range(8):
        lo = i * 45.0
        mean = 1.30 + 0.05 * math.cos(math.radians(lo - 225))  # a little gustier from the SW in the mock
        sectors.append(
            GustSector(
                from_deg=lo,
                to_deg=lo + 45,
                gust_factor=Distribution(dist="lognormal", params={"mean": round(mean, 3), "sigma": 0.08}),
                dir_sigma_deg=15.0,
            )
        )
    end = utcnow().replace(minute=0, second=0, microsecond=0)
    return GustModel(
        station_id=station_id,
        sectors=sectors,
        current_residual_sigma_kt=0.15,
        fitted_on=FitWindow(start_utc=end - timedelta(days=365), end_utc=end, n=87600),
        provenance=Provenance(source="Mock gust model", confidence="mock",
                              notes="Real fit uses 1+ year of 6-minute Willoughby (8638614) wind and gust data."),
    )
