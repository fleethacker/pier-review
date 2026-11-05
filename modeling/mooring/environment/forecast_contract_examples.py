"""Deterministic D2 request/partial-response examples for contract generation."""

from mooring.core.schemas import ComposedForecast, ComposedForecastManifest, ForecastComponentSeries

from .forecast_hashing import component_content_sha256, manifest_revision


def compose_request_example() -> dict:
    return {
        "berth_id": "NAVSTA-NORFOLK-P12-N",
        "source": {"mode": "public", "env_scenario_id": None},
        "as_of_utc": "2026-11-05T05:00:00Z",
        "horizon_start_utc": "2026-11-06T05:00:00Z",
        "horizon_end_utc": "2026-11-06T13:00:00Z",
        "step_min": 60,
        "current_depth_ft": 21.0,
        "current_bin": "4",
    }


def _series(component: str, availability: dict, points: list[dict]) -> dict:
    bound_availability = {"component": component, **availability}
    series = ForecastComponentSeries.model_validate({
        "availability": bound_availability,
        "content_sha256": "0" * 64,
        "points": points,
    })
    return series.model_copy(update={"content_sha256": component_content_sha256(series)}).model_dump(mode="json")


def compose_partial_response_example() -> dict:
    current = [
        {"component": "current", "valid_at_utc": "2026-11-06T05:00:00Z", "current_speed_kt": 0.36,
         "current_set_true_deg": 353.0, "original": {"speed_kt": 0.36, "direction_deg": 353.0}},
        {"component": "current", "valid_at_utc": "2026-11-06T13:00:00Z", "current_speed_kt": 0.63,
         "current_set_true_deg": 2.0, "original": {"speed_kt": 0.63, "direction_deg": 2.0}},
    ]
    water = [
        {"component": "water_level", "valid_at_utc": "2026-11-06T05:00:00Z", "water_level_mllw_ft": 1.77,
         "original": {"water_level_ft_mllw": 1.77}},
        {"component": "water_level", "valid_at_utc": "2026-11-06T13:00:00Z", "water_level_mllw_ft": 1.43,
         "original": {"water_level_ft_mllw": 1.43}},
    ]
    components = [
        {
            "availability": {
                "component": "wind",
                "state": "unavailable",
                "quality": "unknown",
                "limitations": [],
                "reason": "NWS wind forecast unavailable for the requested horizon",
            },
            "content_sha256": None,
            "points": [],
        },
        _series("current", {
            "state": "prediction",
            "source": "NOAA CO-OPS cb0402 currents_predictions bin 4",
            "basis": "prediction",
            "retrieved_at_utc": "2026-11-05T04:41:00Z",
            "valid_from_utc": "2026-11-06T05:00:00Z",
            "valid_to_utc": "2026-11-06T13:00:00Z",
            "quality": "unknown",
            "limitations": [
                "Retrieval establishes available-by time, not provider issuance or forecast freshness.",
                "Station bin guidance is not a qualified pier-wide or vessel-draft current profile.",
            ],
            "station_id": "cb0402",
            "current_depth_ft": 21.0,
            "current_bin": "4",
        }, current),
        _series("water_level", {
            "state": "prediction",
            "source": "NOAA CO-OPS 8638610 water_level predictions",
            "basis": "prediction",
            "retrieved_at_utc": "2026-11-05T04:41:00Z",
            "valid_from_utc": "2026-11-06T05:00:00Z",
            "valid_to_utc": "2026-11-06T13:00:00Z",
            "quality": "unknown",
            "limitations": ["Retrieval establishes available-by time, not provider issuance or forecast freshness."],
            "station_id": "8638610",
            "vertical_datum": "MLLW",
        }, water),
    ]
    manifest = ComposedForecastManifest.model_validate({
        "schema_version": "composed-forecast-v1",
        "revision": "sha256:" + "0" * 64,
        "request": compose_request_example(),
        "status": "partial",
        "components": components,
        "limitations": ["CO-OPS-only fallback: wind is unavailable, so no complete load-model snapshot is emitted."],
    })
    manifest = manifest.model_copy(update={"revision": manifest_revision(manifest)})
    return ComposedForecast(manifest=manifest, snapshots=[]).model_dump(mode="json")
