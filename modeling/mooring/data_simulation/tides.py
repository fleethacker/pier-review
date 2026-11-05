"""Legacy synthetic tide fixture, isolated for training and explicitly not a forecast."""
from mooring import environment


def legacy_tide_levels(berth, times):
    stations = (berth.env_station_ids.wind, berth.env_station_ids.current, berth.env_station_ids.water_level)
    return [(at, environment.synthetic(at, 'scenario', stations).water_level_mllw_ft) for at in times]
