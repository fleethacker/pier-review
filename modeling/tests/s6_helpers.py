"""Shared builders for the S6 transit benchmarks."""

from mooring.core.schemas import EnvironmentSnapshot, TransitRequest
from mooring.transit import simulator as S

FT = 0.3048


def far_route(heading=0.0, speed=30.0):
    """A very distant waypoint ahead so scripted-helm runs never arrive or switch legs."""
    import math
    d = 0.9  # degrees of latitude/longitude, ~100 km
    return [{"lat": 37.0 + d * math.cos(math.radians(heading)), "lon": -76.0 + d * math.sin(math.radians(heading)), "speed_kt": speed}]


def vessel(vid="A", cls="DDG-51-FIIA", speed=0.0, heading=0.0, helm=None, route=None, **kw):
    d = {"vessel_id": vid, "ship_class_id": cls, "start": {"lat": 37.0, "lon": -76.0, "heading_true_deg": heading, "speed_kt": speed},
         "route": route or far_route(heading), "helm_commands": helm or []}
    d.update(kw)
    return d


def request(vessels, dur=600.0, dt=0.2, env=None, sample=None, **kw):
    d = {"vessels": vessels, "duration_s": dur, "dt_s": dt, "origin": {"lat": 37.0, "lon": -76.0}}
    if env:
        d["environment"] = env
    if sample:
        d["sample_interval_s"] = sample
    d.update(kw)
    return TransitRequest.model_validate(d)


def env(wind_kt=0.0, wind_from=0.0, cur_kt=0.0, cur_toward=0.0):
    return EnvironmentSnapshot(wind_speed_kt=wind_kt, wind_gust_kt=wind_kt, wind_from_true_deg=wind_from,
                               current_speed_kt=cur_kt, current_set_true_deg=cur_toward, water_level_mllw_ft=0.0).model_dump(mode="json")


def run(vessels, **kw):
    return S.run(request(vessels, **kw))


def states(r, vid="A"):
    return [next(v for v in f.vessels if v.vessel_id == vid) for f in r.frames]
