"""D4 contract-first coverage for offshore waves and honest berth gaps."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from modeling_api.main import openapi_schema
from modeling_api.routers.env import env_waves_compose
from mooring.core.schemas import (
    ComposedWaveManifest,
    ComposedWaves,
    EnvironmentComponentAvailability,
    OffshoreWavePoint,
    OffshoreWaveSeries,
    WaveComposeRequest,
    WaveBulkParameters,
    WaveSourceLocation,
    WaveSpectrum,
)
from mooring.environment.forecast_hashing import component_content_sha256, manifest_revision
from mooring.environment.wave_contract_examples import (
    wave_compose_partial_response_example,
    wave_compose_request_example,
)


EXPORTED = Path(__file__).parents[2] / "contract/examples/modeling/env_waves_compose_partial.json"


def _gfs_series(*, times: list[str], coverage: str = "complete", issued: str | None = "2026-11-05T12:30:00Z"):
    availability = EnvironmentComponentAvailability.model_validate({
        "component": "waves",
        "state": "prediction",
        "source": "NOAA/NCEP GFS-Wave atlocn.0p16",
        "basis": "prediction",
        "issued_at_utc": issued,
        "retrieved_at_utc": "2026-11-05T12:45:00Z",
        "valid_from_utc": times[0],
        "valid_to_utc": times[-1],
        "grid_cell": "atlocn.0p16:row109,col146",
        "limitations": ["Offshore model grid guidance; no berth transfer is established."],
    })
    points = [OffshoreWavePoint.model_validate({
        "valid_at_utc": value,
        "timestamp_basis": "instant",
        "total_sea": {
            "component": "total_sea", "significant_height_ft": 3.0,
            "period_s": 8.0, "period_basis": "primary_mean",
            "direction_from_true_deg": 110.0, "direction_basis": "primary",
        },
    }) for value in times]
    series = OffshoreWaveSeries.model_construct(
        role="forecast",
        provider="gfs-wave",
        model_id="gfs-wave",
        reference_time_utc=datetime(2026, 11, 5, 12, tzinfo=UTC),
        coverage=coverage,
        availability=availability,
        product_ids=["gfswave.t12z.atlocn.0p16"],
        location=WaveSourceLocation(
            latitude_deg=55 - 109 / 6, longitude_deg=260 + 146 / 6 - 360, grid_cell="atlocn.0p16:row109,col146"
        ),
        content_sha256="0" * 64,
        points=points,
    )
    bound = series.model_copy(update={"content_sha256": component_content_sha256(series)})
    return OffshoreWaveSeries.model_validate(bound.model_dump(mode="json"))


def test_partial_example_preserves_offshore_data_without_claiming_berth_forcing():
    response = ComposedWaves.model_validate(wave_compose_partial_response_example())
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].availability.state == "live"
    assert by_role["forecast"].coverage == "unavailable" and by_role["forecast"].points == []
    point = by_role["observation"].points[0]
    assert point.total_sea.component == "total_sea"
    assert {item.component for item in point.partitions} == {"swell", "wind_sea"}
    assert by_role["observation"].representation_policy == "choose_total_or_partitions_or_spectrum"
    assert by_role["observation"].load_ready is False
    assert by_role["observation"].points[1].spectrum.density_coverage == "partial"
    assert all(item.state == "unavailable" for item in response.manifest.berth_exposure)
    assert next(item for item in response.manifest.berth_exposure if item.component == "ocean_swell").reason_code == "NO_BERTH_WAVE_TRANSFER"


def test_manifest_revision_binds_provider_content_and_applicability_policy():
    manifest = ComposedWaveManifest.model_validate(wave_compose_partial_response_example()["manifest"])
    assert manifest.revision == manifest_revision(manifest)
    observation = manifest.offshore_series[0]
    assert observation.content_sha256 == component_content_sha256(observation)
    changed = manifest.model_copy(update={
        "berth_exposure": [
            item.model_copy(update={"reason": item.reason + " changed"}) if item.component == "ocean_swell" else item
            for item in manifest.berth_exposure
        ]
    })
    assert manifest.revision != manifest_revision(changed)


def test_stale_series_or_manifest_hashes_are_rejected():
    raw = wave_compose_partial_response_example()
    raw["manifest"]["offshore_series"][0]["points"][0]["total_sea"]["significant_height_ft"] = 99
    with pytest.raises(ValidationError, match="content_sha256"):
        ComposedWaves.model_validate(raw)
    raw = wave_compose_partial_response_example()
    raw["manifest"]["limitations"].append("tampered")
    with pytest.raises(ValidationError, match="revision"):
        ComposedWaves.model_validate(raw)


def test_exported_partial_response_is_generated_and_validated():
    assert json.loads(EXPORTED.read_text()) == wave_compose_partial_response_example()
    ComposedWaves.model_validate_json(EXPORTED.read_text())


def test_request_cutoff_and_horizon_are_explicit_and_bounded():
    request = WaveComposeRequest.model_validate(wave_compose_request_example())
    assert request.observation_station_id == "44099" and request.forecast_source == "gfs-wave"
    bad = wave_compose_request_example()
    bad["horizon_start_utc"] = "2026-11-05T16:29:59Z"
    with pytest.raises(ValidationError, match="cannot begin before"):
        WaveComposeRequest.model_validate(bad)
    bad = wave_compose_request_example()
    bad["horizon_end_utc"] = "2026-11-11T16:30:00Z"
    with pytest.raises(ValidationError, match="120 hours"):
        WaveComposeRequest.model_validate(bad)


def test_spectrum_keeps_native_bins_without_reconstructing_direction():
    density = WaveSpectrum.model_validate({
        "representation": "frequency_density",
        "frequency_bin_count": 3,
        "density_coverage": "complete",
        "bins": [
            {"frequency_hz": 0.09, "energy_density_m2_per_hz": 0.099},
            {"frequency_hz": 0.095, "energy_density_m2_per_hz": 0.508},
            {"frequency_hz": 0.101, "energy_density_m2_per_hz": 0.521},
        ],
    })
    assert density.bins[1].alpha1_direction_from_true_deg is None
    with pytest.raises(ValidationError, match="cannot carry directional"):
        WaveSpectrum.model_validate({
            **density.model_dump(),
            "alpha1_coverage": "complete",
            "bins": [
                {**item.model_dump(), "alpha1_direction_from_true_deg": 121}
                for item in density.bins
            ],
        })
    with pytest.raises(ValidationError, match="strictly increasing"):
        WaveSpectrum.model_validate({
            **density.model_dump(),
            "bins": list(reversed(density.model_dump()["bins"])),
        })
    directional = WaveSpectrum.model_validate({
        **density.model_dump(),
        "representation": "ndbc_fourier_coefficients",
        "alpha1_coverage": "complete",
        "r1_coverage": "partial",
        "bins": [
            {
                **item.model_dump(),
                "alpha1_direction_from_true_deg": 120 + index,
                "r1": 0.5 if index == 1 else None,
            }
            for index, item in enumerate(density.bins)
        ],
    })
    assert directional.alpha1_coverage == "complete" and directional.r1_coverage == "partial"
    coefficients_only = WaveSpectrum.model_validate({
        "representation": "ndbc_fourier_coefficients",
        "frequency_bin_count": 2,
        "density_coverage": "unavailable",
        "alpha1_coverage": "complete",
        "bins": [
            {"frequency_hz": 0.09, "alpha1_direction_from_true_deg": 121},
            {"frequency_hz": 0.095, "alpha1_direction_from_true_deg": 124},
        ],
    })
    assert all(item.energy_density_m2_per_hz is None for item in coefficients_only.bins)


def test_missing_partitions_and_unknown_sample_bounds_stay_missing():
    point = OffshoreWavePoint(
        valid_at_utc="2026-11-05T16:00:00Z",
        timestamp_basis="unknown",
        total_sea={"component": "total_sea", "significant_height_ft": 3.6},
    )
    assert point.partitions == [] and point.spectrum is None
    assert point.sample_start_utc is None and point.sample_end_utc is None
    with pytest.raises(ValidationError, match="cannot be repeated"):
        OffshoreWavePoint(
            valid_at_utc="2026-11-05T16:00:00Z",
            partitions=[{"component": "total_sea", "significant_height_ft": 3.6}],
        )


def test_bulk_contract_can_preserve_gfs_native_period_and_direction_semantics():
    total = WaveBulkParameters(
        component="total_sea",
        significant_height_ft=3.6,
        period_s=8.0,
        period_basis="primary_mean",
        direction_from_true_deg=115.0,
        direction_basis="primary",
    )
    partition = WaveBulkParameters(
        component="wind_sea",
        significant_height_ft=2.1,
        period_s=6.0,
        period_basis="provider_partition_mean",
        direction_from_true_deg=125.0,
        direction_basis="provider_partition",
    )
    assert total.period_basis == "primary_mean" and total.direction_basis == "primary"
    assert partition.period_basis == "provider_partition_mean"


def test_manifest_requires_all_source_roles_and_distinct_berth_exposures():
    raw = wave_compose_partial_response_example()["manifest"]
    raw["offshore_series"][-1] = raw["offshore_series"][0]
    with pytest.raises(ValidationError, match="observation, forecast and independent_check"):
        ComposedWaveManifest.model_validate(raw)
    raw = wave_compose_partial_response_example()["manifest"]
    raw["berth_exposure"][-1] = raw["berth_exposure"][0]
    with pytest.raises(ValidationError, match="all four distinct"):
        ComposedWaveManifest.model_validate(raw)


def test_manifest_binds_structured_sources_to_request():
    raw = wave_compose_partial_response_example()["manifest"]
    observation = raw["offshore_series"][0]
    observation.update(coverage="unavailable", station_id="99999", content_sha256=None, points=[])
    observation["availability"].update(state="unavailable", station_id="99999", reason="station unavailable")
    with pytest.raises(ValidationError, match="station does not match"):
        ComposedWaveManifest.model_validate(raw)


def test_available_gfs_requires_timing_and_complete_coverage_has_no_large_gaps():
    times = ["2026-11-05T16:30:00Z", "2026-11-06T16:30:00Z"]
    forecast = _gfs_series(times=times)
    raw = wave_compose_partial_response_example()["manifest"]
    raw["offshore_series"][1] = forecast.model_dump(mode="json")
    with pytest.raises(ValidationError, match="maximum gap"):
        ComposedWaveManifest.model_validate(raw)
    with pytest.raises(ValidationError, match="reference and issue times"):
        _gfs_series(times=times, issued=None)


def test_available_gfs_and_recorded_ndbc_states_validate_when_bound():
    times = [f"2026-11-{day:02d}T{hour:02d}:30:00Z" for day, hour in [
        (5, 16), (5, 19), (5, 22), (6, 1), (6, 4), (6, 7), (6, 10), (6, 13), (6, 16)
    ]]
    raw = wave_compose_partial_response_example()["manifest"]
    raw["offshore_series"][1] = _gfs_series(times=times).model_dump(mode="json")
    observation = raw["offshore_series"][0]
    observation["availability"]["state"] = "replay"
    observation["content_sha256"] = component_content_sha256(observation)
    raw["revision"] = manifest_revision(raw)
    manifest = ComposedWaveManifest.model_validate(raw)
    assert manifest.offshore_series[0].availability.state == "replay"
    assert manifest.offshore_series[1].coverage == "complete"


def test_sample_completion_and_spectrum_request_are_enforced():
    raw = wave_compose_partial_response_example()["manifest"]
    point = raw["offshore_series"][0]["points"][0]
    point.update(
        sample_start_utc="2026-11-05T15:56:00Z",
        sample_end_utc="2026-11-05T16:27:00Z",
        timestamp_basis="start",
    )
    raw["offshore_series"][0]["availability"]["valid_to_utc"] = "2026-11-05T16:27:00Z"
    raw["offshore_series"][0]["content_sha256"] = component_content_sha256(raw["offshore_series"][0])
    with pytest.raises(ValidationError, match="cannot follow its recorded retrieval"):
        ComposedWaveManifest.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]
    observation = raw["offshore_series"][0]
    observation["availability"]["retrieved_at_utc"] = "2026-11-05T15:55:00Z"
    observation["content_sha256"] = component_content_sha256(observation)
    with pytest.raises(ValidationError, match="cannot follow its recorded retrieval"):
        ComposedWaveManifest.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]
    raw["request"]["include_spectrum"] = False
    with pytest.raises(ValidationError, match="spectra excluded"):
        ComposedWaveManifest.model_validate(raw)


def test_coverage_validity_age_grid_and_reason_codes_are_bound():
    raw = wave_compose_partial_response_example()["manifest"]
    raw["offshore_series"][0]["coverage"] = "complete"
    raw["offshore_series"][0]["content_sha256"] = component_content_sha256(raw["offshore_series"][0])
    with pytest.raises(ValidationError, match="completeness is undefined"):
        ComposedWaveManifest.model_validate(raw)

    times = ["2026-11-04T16:30:00Z", "2026-11-04T19:30:00Z"]
    with pytest.raises(ValidationError, match="precede the model reference"):
        _gfs_series(times=times, coverage="partial")

    raw = wave_compose_partial_response_example()["manifest"]
    outside = _gfs_series(
        times=["2026-11-07T01:30:00Z", "2026-11-07T04:30:00Z"], coverage="partial"
    )
    raw["offshore_series"][1] = outside.model_dump(mode="json")
    with pytest.raises(ValidationError, match="does not intersect"):
        ComposedWaveManifest.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]
    bracketing_gap = _gfs_series(
        times=["2026-11-05T16:00:00Z", "2026-11-07T01:00:00Z"], coverage="partial"
    )
    raw["offshore_series"][1] = bracketing_gap.model_dump(mode="json")
    with pytest.raises(ValidationError, match="does not intersect"):
        ComposedWaveManifest.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]["offshore_series"][0]
    raw["availability"]["valid_to_utc"] = "2026-11-05T15:59:00Z"
    raw["content_sha256"] = component_content_sha256(raw)
    with pytest.raises(ValidationError, match="last point/sample bound"):
        OffshoreWaveSeries.model_validate(raw)

    forecast = _gfs_series(times=["2026-11-05T16:30:00Z", "2026-11-05T19:30:00Z"], coverage="partial")
    raw = forecast.model_dump(mode="json")
    raw["availability"]["grid_cell"] = "different-cell"
    raw["content_sha256"] = component_content_sha256(raw)
    with pytest.raises(ValidationError, match="same grid cell"):
        OffshoreWaveSeries.model_validate(raw)

    raw = forecast.model_dump(mode="json")
    raw["points"][0]["spectrum"] = {
        "representation": "ndbc_fourier_coefficients",
        "frequency_bin_count": 1,
        "density_coverage": "unavailable",
        "alpha1_coverage": "complete",
        "bins": [{"frequency_hz": 0.09, "alpha1_direction_from_true_deg": 121.0}],
    }
    raw["content_sha256"] = component_content_sha256(raw)
    with pytest.raises(ValidationError, match="cannot carry NDBC Fourier"):
        OffshoreWaveSeries.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]
    raw["offshore_series"][0]["availability"]["age_s"] = 1.0
    raw["offshore_series"][0]["content_sha256"] = component_content_sha256(raw["offshore_series"][0])
    with pytest.raises(ValidationError, match="age contradicts"):
        ComposedWaveManifest.model_validate(raw)

    raw = wave_compose_partial_response_example()["manifest"]
    raw["berth_exposure"][0]["reason_code"] = "NO_WAKE_SOURCE"
    with pytest.raises(ValidationError, match="does not apply"):
        ComposedWaveManifest.model_validate(raw)


def test_contract_publishes_additive_wave_compose_route():
    operation = openapi_schema()["paths"]["/api/v1/env/waves/compose"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/WaveComposeRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ComposedWaves"
    )
    alpha1 = openapi_schema()["components"]["schemas"]["WaveSpectrumBin"]["properties"][
        "alpha1_direction_from_true_deg"
    ]
    assert "come from" in alpha1["description"] and "true north" in alpha1["description"]


def test_route_dispatches_without_rewriting_the_bound_request(monkeypatch):
    request = WaveComposeRequest.model_validate(wave_compose_request_example())
    expected = ComposedWaves.model_validate(wave_compose_partial_response_example())
    monkeypatch.setattr("modeling_api.routers.env.impl.compose_waves", lambda value: expected if value == request else None)
    assert env_waves_compose(request) == expected
