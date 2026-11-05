"""Deterministic D4 request and honest offshore-only response examples."""

from mooring.core.schemas import (
    ComposedWaveManifest,
    ComposedWaves,
    EnvironmentComponentAvailability,
    OffshoreWavePoint,
    OffshoreWaveSeries,
    WaveBerthExposureAvailability,
    WaveComposeRequest,
    WaveSourceLocation,
)

from .forecast_hashing import component_content_sha256, manifest_revision


def wave_compose_request_example() -> dict:
    return {
        "berth_id": "NAVSTA-NORFOLK-P12-N",
        "as_of_utc": "2026-11-05T16:30:00Z",
        "horizon_start_utc": "2026-11-05T16:30:00Z",
        "horizon_end_utc": "2026-11-06T16:30:00Z",
        "observation_lookback_hours": 24,
        "max_forecast_gap_hours": 3,
        "observation_station_id": "44099",
        "independent_check_station_id": "44014",
        "forecast_source": "gfs-wave",
        "include_spectrum": True,
    }


def _observation_series() -> dict:
    availability = EnvironmentComponentAvailability.model_validate({
            "component": "waves",
            "state": "live",
            "source": "NOAA/NDBC station 44099 detailed wave summary",
            "basis": "observation",
            "age_s": 1800,
            "age_basis": "valid_time",
            "retrieved_at_utc": "2026-11-05T16:26:24Z",
            "valid_from_utc": "2026-11-05T15:56:00Z",
            "valid_to_utc": "2026-11-05T16:00:00Z",
            "quality": "unknown",
            "limitations": [
                "Provider sample bounds are not documented by this response and remain unknown.",
                "Station 44099 is an offshore boundary condition; no berth transfer is established.",
            ],
            "station_id": "44099",
    })
    points = [OffshoreWavePoint.model_validate({
            "valid_at_utc": "2026-11-05T15:56:00Z",
            "timestamp_basis": "unknown",
            "total_sea": {
                "component": "total_sea",
                "significant_height_ft": 3.608924,
                "period_s": 5.8,
                "period_basis": "average",
                "direction_from_true_deg": 121.0,
                "direction_basis": "dominant",
            },
            "partitions": [
                {
                    "component": "swell",
                    "significant_height_ft": 0.656168,
                    "period_s": 10.5,
                    "period_basis": "provider_partition",
                    "direction_from_true_deg": 112.5,
                    "direction_basis": "provider_partition",
                },
                {
                    "component": "wind_sea",
                    "significant_height_ft": 3.608924,
                    "period_s": 9.1,
                    "period_basis": "provider_partition",
                    "direction_from_true_deg": 112.5,
                    "direction_basis": "provider_partition",
                },
            ],
            "original": {
                "WVHT_m": 1.1, "SwH_m": 0.2, "SwP_s": 10.5, "WWH_m": 1.1,
                "WWP_s": 9.1, "SwD": "ESE", "WWD": "ESE", "APD_s": 5.8, "MWD_degT": 121,
            },
        }), OffshoreWavePoint.model_validate({
            "valid_at_utc": "2026-11-05T16:00:00Z",
            "timestamp_basis": "unknown",
            "spectrum": {
                "representation": "frequency_density",
                "frequency_bin_count": 56,
                "density_coverage": "partial",
                "bins": [
                    {"frequency_hz": 0.09, "energy_density_m2_per_hz": 0.099,
                     "quality_flags": ["contract example excerpt; source record has 56 bins"]},
                    {"frequency_hz": 0.095, "energy_density_m2_per_hz": 0.508,
                     "quality_flags": ["contract example excerpt; source record has 56 bins"]},
                    {"frequency_hz": 0.101, "energy_density_m2_per_hz": 0.521,
                     "quality_flags": ["contract example excerpt; source record has 56 bins"]},
                ],
            },
            "original": {"Sep_Freq": 9.999, "source_product": "44099.data_spec"},
        })]
    series = OffshoreWaveSeries.model_construct(
        role="observation",
        provider="ndbc",
        station_id="44099",
        coverage="partial",
        availability=availability,
        product_ids=["NDBC realtime2 44099.spec", "NDBC realtime2 44099.data_spec"],
        location=WaveSourceLocation(latitude_deg=36.915, longitude_deg=-75.722, water_depth_m=15.0),
        content_sha256="0" * 64,
        points=points,
    )
    bound = series.model_copy(update={"content_sha256": component_content_sha256(series)})
    return OffshoreWaveSeries.model_validate(bound.model_dump(mode="json")).model_dump(mode="json")


def wave_compose_partial_response_example() -> dict:
    unavailable = [
        {
            "role": "forecast",
            "provider": "gfs-wave",
            "station_id": None,
            "model_id": "gfs-wave",
            "coverage": "unavailable",
            "availability": {
                "component": "waves", "state": "unavailable", "source": "NOAA/NCEP GFS-Wave",
                "basis": "prediction", "quality": "unknown", "limitations": [],
                "reason": "No forecast artifact available by the request as_of time.",
            },
            "product_ids": [], "location": None, "content_sha256": None, "points": [],
        },
        {
            "role": "independent_check",
            "provider": "ndbc",
            "station_id": "44014",
            "model_id": None,
            "coverage": "unavailable",
            "availability": {
                "component": "waves", "state": "unavailable", "source": "NOAA/NDBC station 44014",
                "basis": "observation", "quality": "unknown", "limitations": [],
                "reason": "Independent comparison was not acquired for this manifest.",
                "station_id": "44014",
            },
            "product_ids": [], "location": None, "content_sha256": None, "points": [],
        },
    ]
    berth_exposure = [
        {
            "component": "ocean_swell", "state": "unavailable", "reason_code": "NO_BERTH_WAVE_TRANSFER",
            "reason": "No validated transformation from the offshore boundary to this berth.",
            "limitations": ["Offshore values cannot be copied into berth forcing."],
        },
        {
            "component": "local_chop", "state": "unavailable", "reason_code": "NO_DIRECTIONAL_FETCH",
            "reason": "No reviewed directional fetch geometry is available for this berth.", "limitations": [],
        },
        {
            "component": "ship_wake", "state": "unavailable", "reason_code": "NO_WAKE_SOURCE",
            "reason": "No approved traffic feed and berth-validated ship-wake model are available.", "limitations": [],
        },
        {
            "component": "tug_wake", "state": "unavailable", "reason_code": "NO_WAKE_SOURCE",
            "reason": "No berth-validated tug-wake source or response model is available.", "limitations": [],
        },
    ]
    series = [OffshoreWaveSeries.model_validate(item) for item in [_observation_series(), *unavailable]]
    exposures = [WaveBerthExposureAvailability.model_validate(item) for item in berth_exposure]
    manifest = ComposedWaveManifest.model_construct(
        revision="sha256:" + "0" * 64,
        request=WaveComposeRequest.model_validate(wave_compose_request_example()),
        offshore_series=series,
        berth_exposure=exposures,
        limitations=[
            "Total sea, provider partitions and spectra are alternative representations and must not be summed.",
            "NDBC 44099 is about 54 km from the berth and is exposed only as an offshore boundary condition.",
            "GFS-Wave forecast guidance is unavailable in this example; missing guidance is not replaced with zero waves.",
        ],
    )
    bound = manifest.model_copy(update={"revision": manifest_revision(manifest)})
    validated = ComposedWaveManifest.model_validate(bound.model_dump(mode="json"))
    return ComposedWaves(manifest=validated).model_dump(mode="json")
