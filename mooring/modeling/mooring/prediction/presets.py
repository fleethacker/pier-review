"""S7 demonstration scenarios built from the recorded NOAA CO-OPS window (fixtures/noaa_live, 2026-11-05 17:11 UTC).

The environment is REAL (one recorded moment); the vessel state is a demonstration placement, not a real ship."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from mooring import refdata
from mooring.core.schemas import PredictionPreset, PredictionRequest, Validity, ValidityReason
from mooring.environment import coops, live
from mooring.transit.geo import LocalPlane

FIX = Path(__file__).parent / "fixtures" / "noaa_live"
BERTH = "NAVSTA-NORFOLK-P12-N"
AS_OF = datetime(2026, 11, 5, 17, 11, tzinfo=UTC)
FILES = {"wind": "wind_8638614.json", "water_level": "water_level_8638610.json", "currents": "currents_cb0402_bin4.json",
         "currents_predictions": "currents_predictions_cb0402_bin4.json"}


@lru_cache(maxsize=1)
def noaa_snapshot():
    def transport(url, params, timeout):
        return 200, (FIX / FILES[params["product"]]).read_text()
    clock = lambda: AS_OF  # noqa: E731
    live.configure(coops.Fetcher(transport, clock=clock, sleep=lambda s: None, retries=0, min_interval_s=0.0), clock=clock)
    try:
        return live.latest(BERTH)
    finally:
        live.configure()


def _geo_off_pier(off_ft: float):
    b = refdata.berth(BERTH)
    plane = LocalPlane(b.origin_lat, b.origin_lon)
    mid = b.face_length_ft / 2 * 0.3048
    t = math.radians(b.face_bearing_true_deg)
    w = math.radians(b.face_bearing_true_deg - 90.0)
    d = off_ft * 0.3048
    lat, lon = plane.to_geo(mid * math.sin(t) + d * math.sin(w), mid * math.cos(t) + d * math.cos(w))
    return lat, lon, (b.face_bearing_true_deg + 90.0) % 360     # heading toward the face


def approach_request(off_ft=2430.0, surge_kt=4.0, engine_order=0.03, samples=16, seed=7, horizon_s=420.0, alternatives=True,
                     vessel_id="DDG-51-demo", observed_s_ago=2.0) -> PredictionRequest:
    lat, lon, hdg = _geo_off_pier(off_ft)
    from datetime import timedelta
    d = {"vessel": {"vessel_id": vessel_id, "ship_class_id": "DDG-51-FIIA", "observed_utc": (AS_OF - timedelta(seconds=observed_s_ago)).isoformat(),
                    "position": {"lat": round(lat, 7), "lon": round(lon, 7)}, "heading_true_deg": round(hdg, 2), "surge_kt": surge_kt,
                    "rudder_deg": 1.0, "engine_order": engine_order,
                    "uncertainty": {"position_sd_ft": 15, "heading_sd_deg": 1, "speed_sd_kt": 0.2}, "source": "demonstration"},
         "environment": noaa_snapshot().model_dump(mode="json"), "as_of_utc": AS_OF.isoformat(), "horizon_s": horizon_s, "tick_s": 10,
         "uncertainty": {"samples": samples, "seed": seed}, "hazards": {"berth_id": BERTH, "coastline": True, "min_clearance_ft": 50}}
    if alternatives:
        d["alternatives"] = [
            {"alt_id": "more-rudder", "label": "Rudder 15 to port now", "helm_commands": [{"t_s": 0, "rudder_deg": 15}]},
            {"alt_id": "tug-push", "label": "Tug pushes the bow to port (270 deg relative)",
             "tug_commands": [{"t_s": 0, "tug_id": "T1", "point": "bow", "force_lbf": 30000, "direction_rel_deg": 270}]}]
    return PredictionRequest.model_validate(d)


def _validity(what: str) -> Validity:
    return Validity(state="limited", reasons=[ValidityReason(code="DEMONSTRATION_SCENARIO",
                    message=f"{what}: real recorded NOAA conditions for one moment, but a demonstration vessel placement; not a real ship, not navigational advice.")])


def presets() -> list[PredictionPreset]:
    return [
        PredictionPreset(preset_id="approach-pier-12-4kt", title="Approaching Pier 12 at 4 kt: hold vs more rudder vs tug push",
                         request=approach_request(), validity=_validity("Approach to NAVSTA Norfolk Pier 12 north face")),
        PredictionPreset(preset_id="passing-piers-8kt", title="Passing the piers at 8 kt",
                         request=approach_request(off_ft=1200.0, surge_kt=8.0, engine_order=0.35, samples=8, horizon_s=180.0,
                                                  alternatives=False, vessel_id="DDG-51-pass"),
                         validity=_validity("Passing NAVSTA Norfolk Pier 12")),
    ]
