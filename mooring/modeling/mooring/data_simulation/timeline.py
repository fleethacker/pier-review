"""Adapter for the legacy training timeline; never a substitute for public forecasts."""
from mooring import environment
from mooring.core.schemas import EnvironmentMetadata, StationQuality


def sample(at, stations):
    return environment.synthetic(at, "scenario", stations).model_copy(update={
        "metadata": EnvironmentMetadata(basis="scenario", source="legacy synthetic training timeline",
            wind_averaging_s=60, gust_duration_s=30, wind_reference_height_m=10,
            vertical_datum="MLLW", quality="unknown"),
        "quality": [StationQuality(station_id="synthetic-training", age_s=0,
                                   flags=["synthetic", "not_a_forecast"])],
    })
