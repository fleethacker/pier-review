"""D4 provider parsing/composition tests; no test reaches a network."""

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from modeling_api.main import app
from mooring.core.schemas import WaveComposeRequest
from mooring.environment import waves
from mooring.environment.errors import ProviderError
from mooring.environment.forecast_hashing import component_content_sha256, manifest_revision
from mooring.environment.gfs_wave_artifact import artifact_revision, load_artifact
from mooring.environment.ndbc import (
    FetchedProduct,
    NDBCRealtime,
    NDBCStationAdapter,
    merge_spectral_products,
    parse_spectral_product,
    parse_summary,
)
from mooring.environment.providers import HttpPayload, bounded_httpx_transport
from mooring.environment.waves import WaveComposer

FIXTURES = Path(__file__).parents[1] / "mooring/environment/fixtures/ndbc"
AS_OF = datetime(2026, 11, 5, 16, 30, tzinfo=UTC)
END = AS_OF + timedelta(hours=12)
BERTH = "NAVSTA-NORFOLK-P12-N"


class FixtureRealtime:
    def __init__(self, *, fail_stations=(), retrieved_at=AS_OF - timedelta(minutes=3, seconds=36)):
        self.fail_stations = set(fail_stations)
        self.retrieved_at = retrieved_at

    def fetch(self, station_id, product):
        if station_id in self.fail_stations:
            raise ProviderError("unavailable", f"fixture outage for {station_id}")
        path = FIXTURES / f"{station_id}.{product}"
        if not path.exists():
            raise ProviderError("no_data", f"fixture has no {station_id}.{product}")
        return FetchedProduct(
            text=path.read_text(),
            retrieved_at_utc=self.retrieved_at,
            source_url=f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.{product}",
        )


class MalformedSpectrumRealtime(FixtureRealtime):
    def fetch(self, station_id, product):
        fetched = super().fetch(station_id, product)
        if station_id == "44099" and product == "data_spec":
            return FetchedProduct("not a native NDBC row\n", fetched.retrieved_at_utc, fetched.source_url)
        return fetched


def request(**changes):
    values = {
        "berth_id": BERTH,
        "as_of_utc": AS_OF,
        "horizon_start_utc": AS_OF,
        "horizon_end_utc": END,
        "observation_lookback_hours": 24,
        "max_forecast_gap_hours": 3,
        "include_spectrum": True,
    }
    return WaveComposeRequest(**(values | changes))


def gfs_artifact(tmp_path, *, end=END, retrieved_at=AS_OF - timedelta(minutes=10), gap_hours=3):
    rows, at = [], AS_OF
    while at <= end:
        rows.append({
            "valid_at_utc": at.isoformat().replace("+00:00", "Z"),
            "total_sea": {
                "significant_height_m": 1.2,
                "height_variable": "HTSGW",
                "period_s": 8.0,
                "period_variable": "PERPW",
                "direction_from_true_deg": 115.0,
                "direction_variable": "DIRPW",
            },
            "swell_partitions": [{
                "partition_id": "swell_1",
                "sequence_level": 1,
                "significant_height_m": 0.4,
                "height_variable": "SWELL",
                "period_s": 10.0,
                "period_variable": "SWPER",
                "direction_from_true_deg": 100.0,
                "direction_variable": "SWDIR",
            }],
            "wind_sea": {
                "significant_height_m": 1.0,
                "height_variable": "WVHGT",
                "period_s": 6.0,
                "period_variable": "WVPER",
                "direction_from_true_deg": 125.0,
                "direction_variable": "WVDIR",
            },
        })
        at += timedelta(hours=gap_hours)
    payload = {
        "schema_version": "gfs-wave-decoded-v1",
        "source": {
            "model_id": "gfs-wave",
            "grid_id": "atlocn.0p16",
            "product_id": "gfswave.t12z.atlocn.0p16.fixture",
            "source_uri": "fixture-gfs-wave.grib2",
            "reference_time_utc": "2026-11-05T12:00:00Z",
            "issued_at_utc": "2026-11-05T12:30:00Z",
            "retrieved_at_utc": retrieved_at.isoformat().replace("+00:00", "Z"),
            "publication_evidence": "fixture: decoded GFS-Wave unit-test artifact",
        },
        "location": {
            "latitude_deg": 36.96,
            "longitude_deg": -75.68,
            "grid_cell": "atlocn.0p16:36.96,-75.68",
        },
        "rows": rows,
        "limitations": ["Decoded unit-test artifact; no harbor transformation."],
    }
    payload["revision"] = artifact_revision(payload)
    path = tmp_path / "gfs-wave.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return path


@pytest.fixture(autouse=True)
def reset_composer():
    yield
    waves.configure(None)


def test_ndbc_summary_preserves_units_directions_partitions_and_missingness():
    points = parse_summary((FIXTURES / "44099.spec").read_text())
    latest = points[0]
    assert latest.total_sea.significant_height_ft == pytest.approx(1.1 * 3.28084)
    assert latest.total_sea.period_basis == "average"
    assert latest.total_sea.direction_from_true_deg == 123.0
    assert latest.total_sea.direction_basis == "dominant"
    by_component = {item.component: item for item in latest.partitions}
    assert by_component["swell"].direction_from_true_deg == 112.5
    assert by_component["wind_sea"].direction_from_true_deg == 112.5

    check = parse_summary((FIXTURES / "44014.spec").read_text())[0]
    assert check.total_sea.significant_height_ft == pytest.approx(1.4 * 3.28084)
    assert check.partitions == []


def test_ndbc_native_density_and_alpha1_are_merged_without_reconstruction():
    spectra = merge_spectral_products({
        "data_spec": (FIXTURES / "44099.data_spec").read_text(),
        "swdir": (FIXTURES / "44099.swdir").read_text(),
    })
    spectrum, original = spectra[datetime(2026, 11, 5, 16, tzinfo=UTC)]
    assert spectrum.representation == "ndbc_fourier_coefficients"
    assert spectrum.frequency_bin_count == 3
    assert spectrum.density_coverage == spectrum.alpha1_coverage == "complete"
    assert spectrum.alpha2_coverage == spectrum.r1_coverage == spectrum.r2_coverage == "unavailable"
    assert spectrum.bins[0].energy_density_m2_per_hz == 0.176
    assert spectrum.bins[0].alpha1_direction_from_true_deg == 120.0
    assert original == {"source_products": "data_spec,swdir"}


def test_ndbc_spectral_parser_rejects_corrupt_tails_and_inconsistent_bins():
    corrupt_tail = "2026 11 05 16 00 9.999 0.176 (0.090) corrupt\n"
    with pytest.raises(ProviderError, match="unparsed"):
        parse_spectral_product(corrupt_tail, "data_spec")
    inconsistent = "\n".join([
        "2026 11 05 16 00 120.0 (0.090) 112.0 (0.095)",
        "2026 11 05 15 30 121.0 (0.090)",
    ])
    with pytest.raises(ProviderError, match="frequency bins change"):
        parse_spectral_product(inconsistent, "swdir")


def test_ndbc_realtime_coefficients_are_dimensionless_and_preserve_missing_values():
    # NOAA measdes.shtml#spec: only monthly/yearly historical r1/r2 files are
    # scaled by 100. The realtime2 products consumed here already use 0..1.
    products = {
        "data_spec": "2026 11 05 16 00 9.999 0.176 (0.090) 0.508 (0.095)",
        "swdir": "2026 11 05 16 00 120.0 (0.090) 125.0 (0.095)",
        "swdir2": "2026 11 05 16 00 118.0 (0.090) 124.0 (0.095)",
        "swr1": "2026 11 05 16 00 0.80 (0.090) 999.00 (0.095)",
        "swr2": "2026 11 05 16 00 0.75 (0.090) 0.70 (0.095)",
    }
    spectrum, _ = merge_spectral_products(products)[datetime(2026, 11, 5, 16, tzinfo=UTC)]
    assert spectrum.density_coverage == spectrum.alpha1_coverage == spectrum.alpha2_coverage == "complete"
    assert spectrum.r1_coverage == "partial" and spectrum.r2_coverage == "complete"
    assert spectrum.bins[0].r1 == 0.80 and spectrum.bins[0].r2 == 0.75
    assert spectrum.bins[1].r1 is None and spectrum.bins[1].r2 == 0.70
    assert spectrum.bins[0].energy_density_m2_per_hz == 0.176
    assert spectrum.bins[0].alpha1_direction_from_true_deg == 120.0


def test_gfs_artifact_size_limit_bounds_the_read(monkeypatch):
    class BoundedRead(io.BytesIO):
        def read(self, size=-1):
            assert size == 33
            return super().read(size)

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: BoundedRead(b"x" * 100))
    with pytest.raises(ProviderError, match="exceeds 32 bytes"):
        load_artifact(Path("unused"), max_artifact_bytes=32)


def test_ndbc_live_reader_bounds_response_size_and_station_elapsed_time():
    client = SimpleNamespace(
        clock=SimpleNamespace(now=lambda: AS_OF),
        get=lambda _url: HttpPayload(200, b"oversized", {}),
    )
    with pytest.raises(ProviderError, match="byte response limit"):
        NDBCRealtime(client, max_product_bytes=3).fetch("44099", "spec")

    ticks = iter([0.0, 26.0])
    bounded = NDBCStationAdapter(
        FixtureRealtime(),
        total_timeout_s=25.0,
        monotonic=lambda: next(ticks),
    )
    with pytest.raises(ProviderError, match="total deadline"):
        bounded.acquire("44099", as_of_utc=AS_OF, lookback_hours=24, include_spectrum=False)


def test_ndbc_retrieval_time_is_the_cached_acquisition_not_the_reader_clock():
    retrieved = AS_OF - timedelta(minutes=10)
    payload = SimpleNamespace(
        status_code=200,
        content=b"provider text",
        stale=False,
        age_s=1.0,
        retrieved_at_utc=retrieved,
    )
    client = SimpleNamespace(
        clock=SimpleNamespace(now=lambda: AS_OF),
        get=lambda _url: payload,
    )
    reader = NDBCRealtime(client)
    assert reader.fetch("44099", "spec").retrieved_at_utc == retrieved
    client.clock.now = lambda: AS_OF + timedelta(minutes=5)
    assert reader.fetch("44099", "spec").retrieved_at_utc == retrieved
    payload.retrieved_at_utc = None
    with pytest.raises(ProviderError, match="no recorded retrieval time"):
        reader.fetch("44099", "spec")


def test_default_http_transport_stops_streaming_at_the_byte_limit(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_bytes(self):
            yield b"123"
            yield b"456"

    monkeypatch.setattr("mooring.environment.providers.httpx.stream", lambda *_args, **_kwargs: Response())
    with pytest.raises(httpx.HTTPError, match="exceeds 5 bytes"):
        bounded_httpx_transport(
            "https://example.test",
            {},
            1,
            {},
            max_response_bytes=5,
            max_elapsed_s=5,
        )

    ticks = iter([0.0, 6.0])
    with pytest.raises(httpx.TimeoutException, match="elapsed limit"):
        bounded_httpx_transport(
            "https://example.test",
            {},
            1,
            {},
            max_response_bytes=10,
            max_elapsed_s=5,
            monotonic=lambda: next(ticks),
        )


def test_composer_keeps_gfs_unavailable_but_returns_both_ndbc_stations():
    composer = WaveComposer(ndbc=NDBCStationAdapter(FixtureRealtime()))
    response = composer.compose(request())
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].availability.state == "live"
    assert by_role["forecast"].availability.state == "unavailable"
    assert by_role["independent_check"].availability.state == "live"
    assert by_role["observation"].points[-1].valid_at_utc == datetime(2026, 11, 5, 16, 26, tzinfo=UTC)
    assert "Scripps/CDIP" in by_role["observation"].availability.source
    spectrum = next(point.spectrum for point in by_role["observation"].points if point.spectrum)
    assert spectrum.representation == "ndbc_fourier_coefficients"
    assert by_role["observation"].content_sha256 == component_content_sha256(by_role["observation"])
    assert response.manifest.revision == manifest_revision(response.manifest)
    assert all(item.state == "unavailable" for item in response.manifest.berth_exposure)


def test_full_observation_lookback_preserves_offset_summary_and_spectral_times():
    # Both products can report twice hourly at different timestamps. Their union
    # over the published 45-day request limit contains 4320 distinct points.
    start = AS_OF - timedelta(days=45) + timedelta(minutes=5)
    summary, density = [], []
    for index in range(45 * 48):
        summary_at = start + timedelta(minutes=30 * index)
        spectral_at = summary_at + timedelta(minutes=15)
        summary.append(summary_at.strftime("%Y %m %d %H %M") + " 1.1 MM MM MM MM MM MM N/A 5.8 123")
        density.append(spectral_at.strftime("%Y %m %d %H %M") + " 9.999 0.2 (0.090)")

    class LongRealtime(FixtureRealtime):
        def fetch(self, station_id, product):
            if station_id != "44099":
                return super().fetch(station_id, product)
            rows = {"spec": summary, "data_spec": density}.get(product)
            if rows is None:
                raise ProviderError("no_data", "optional product unavailable")
            return FetchedProduct(
                "\n".join(rows),
                AS_OF - timedelta(minutes=1),
                f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.{product}",
            )

    response = WaveComposer(ndbc=NDBCStationAdapter(LongRealtime())).compose(request(observation_lookback_hours=45 * 24))
    observation = next(item for item in response.manifest.offshore_series if item.role == "observation")
    assert observation.availability.state == "live", observation.availability.reason
    assert len(observation.points) == 4320
    assert sum(point.total_sea is not None for point in observation.points) == 2160
    assert sum(point.spectrum is not None for point in observation.points) == 2160


def test_complete_gfs_artifact_preserves_cycle_grid_horizon_and_partitions(tmp_path):
    path = gfs_artifact(tmp_path)
    assert load_artifact(path, allow_fixture=True)["source"]["grid_id"] == "atlocn.0p16"
    rejected = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=path,
    ).compose(request())
    assert next(item for item in rejected.manifest.offshore_series if item.role == "forecast").coverage == "unavailable"
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=path,
        allow_fixture_artifact=True,
    ).compose(request())
    forecast = next(item for item in response.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "complete"
    assert forecast.reference_time_utc == datetime(2026, 11, 5, 12, tzinfo=UTC)
    assert forecast.availability.issued_at_utc == datetime(2026, 11, 5, 12, 30, tzinfo=UTC)
    assert forecast.availability.grid_cell == "atlocn.0p16:36.96,-75.68"
    assert forecast.points[0].total_sea.significant_height_ft == pytest.approx(1.2 * 3.28084)
    assert forecast.points[0].total_sea.period_basis == "primary_mean"
    assert forecast.points[0].total_sea.direction_basis == "primary"
    assert '"significant_height_m":1.2' in forecast.points[0].original["total_sea_native"]
    partitions = {
        (item.component, item.provider_partition_id): item
        for item in forecast.points[0].partitions
    }
    assert set(partitions) == {("provider_partition", "swell_1"), ("wind_sea", None)}
    assert all(item.period_basis == "provider_partition_mean" for item in partitions.values())


def test_malformed_optional_spectrum_does_not_erase_valid_summary_observations():
    response = WaveComposer(ndbc=NDBCStationAdapter(MalformedSpectrumRealtime())).compose(request())
    observation = next(item for item in response.manifest.offshore_series if item.role == "observation")
    assert observation.availability.state == "live"
    assert observation.points
    spectrum = next(point.spectrum for point in observation.points if point.spectrum is not None)
    assert spectrum.density_coverage == "unavailable" and spectrum.alpha1_coverage == "complete"
    assert any("data_spec omitted" in item for item in observation.availability.limitations)


def test_forecast_horizon_between_adjacent_native_samples_is_covered(tmp_path):
    composer = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
    )
    response = composer.compose(request(
        horizon_start_utc=AS_OF + timedelta(minutes=15),
        horizon_end_utc=AS_OF + timedelta(minutes=75),
    ))
    forecast = next(item for item in response.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "complete"
    assert [point.valid_at_utc for point in forecast.points] == [AS_OF, AS_OF + timedelta(hours=3)]
    assert all(point.total_sea.significant_height_ft == pytest.approx(1.2 * 3.28084) for point in forecast.points)


@pytest.mark.parametrize("offset_hours,gap_hours", [(0, 6), (24, 3)])
def test_forecast_without_an_inside_sample_requires_a_valid_bracket(tmp_path, offset_hours, gap_hours):
    composer = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path, gap_hours=gap_hours),
        allow_fixture_artifact=True,
    )
    start = AS_OF + timedelta(hours=offset_hours, minutes=15)
    response = composer.compose(request(horizon_start_utc=start, horizon_end_utc=start + timedelta(hours=1)))
    forecast = next(item for item in response.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "unavailable" and forecast.points == []
    assert "neither brackets nor has a point" in forecast.availability.reason


def test_uncovered_or_unpublished_gfs_artifacts_do_not_claim_complete_guidance(tmp_path):
    partial = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path, end=AS_OF + timedelta(hours=6)),
        allow_fixture_artifact=True,
    ).compose(request())
    forecast = next(item for item in partial.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "partial"

    late_path = gfs_artifact(tmp_path, retrieved_at=AS_OF + timedelta(seconds=1))
    late = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=late_path,
        allow_fixture_artifact=True,
    ).compose(request())
    forecast = next(item for item in late.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "unavailable"
    assert "after request as_of_utc" in forecast.availability.reason

    malformed_path = gfs_artifact(tmp_path)
    malformed = json.loads(malformed_path.read_text())
    malformed["location"]["grid_cell"] = "atlocn.0p16:0.00,0.00"
    malformed["revision"] = artifact_revision(malformed)
    malformed_path.write_text(json.dumps(malformed, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="bind its coordinates"):
        load_artifact(malformed_path, allow_fixture=True)


def test_gfs_artifact_requires_approved_target_and_native_variable_inventory(tmp_path):
    wrong_target_path = gfs_artifact(tmp_path)
    wrong_target = json.loads(wrong_target_path.read_text())
    wrong_target["location"] = {
        "latitude_deg": 0.0,
        "longitude_deg": 0.0,
        "grid_cell": "atlocn.0p16:0.00,0.00",
    }
    wrong_target["revision"] = artifact_revision(wrong_target)
    wrong_target_path.write_text(json.dumps(wrong_target, sort_keys=True, separators=(",", ":")) + "\n")
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=wrong_target_path,
        allow_fixture_artifact=True,
    ).compose(request())
    forecast = next(item for item in response.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "unavailable"
    assert "approved offshore target" in forecast.availability.reason

    wrong_variable_path = gfs_artifact(tmp_path)
    wrong_variable = json.loads(wrong_variable_path.read_text())
    wrong_variable["rows"][0]["total_sea"]["period_variable"] = "PERIOD"
    wrong_variable["revision"] = artifact_revision(wrong_variable)
    wrong_variable_path.write_text(json.dumps(wrong_variable, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="must come from PERPW"):
        load_artifact(wrong_variable_path, allow_fixture=True)

    off_lattice_path = gfs_artifact(tmp_path)
    off_lattice = json.loads(off_lattice_path.read_text())
    off_lattice["location"] = {
        "latitude_deg": 36.95,
        "longitude_deg": -75.68,
        "grid_cell": "atlocn.0p16:36.95,-75.68",
    }
    off_lattice["revision"] = artifact_revision(off_lattice)
    off_lattice_path.write_text(json.dumps(off_lattice, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="grid lattice"):
        load_artifact(off_lattice_path, allow_fixture=True)

    wrong_partition_path = gfs_artifact(tmp_path)
    wrong_partition = json.loads(wrong_partition_path.read_text())
    wrong_partition["rows"][0]["swell_partitions"][0].update(
        partition_id="invented",
        sequence_level=2,
    )
    wrong_partition["revision"] = artifact_revision(wrong_partition)
    wrong_partition_path.write_text(json.dumps(wrong_partition, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="partition_id must bind"):
        load_artifact(wrong_partition_path, allow_fixture=True)


def test_gfs_artifact_binds_cycle_and_official_forecast_lead(tmp_path):
    cycle_path = gfs_artifact(tmp_path)
    cycle = json.loads(cycle_path.read_text())
    cycle["source"]["product_id"] = "gfswave.t00z.atlocn.0p16.fixture"
    cycle["revision"] = artifact_revision(cycle)
    cycle_path.write_text(json.dumps(cycle, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="cycle does not match"):
        load_artifact(cycle_path, allow_fixture=True)

    lead_path = gfs_artifact(tmp_path)
    lead = json.loads(lead_path.read_text())
    lead["rows"][-1]["valid_at_utc"] = "2026-11-21T13:00:00Z"
    lead["revision"] = artifact_revision(lead)
    lead_path.write_text(json.dumps(lead, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="FH000-FH384"):
        load_artifact(lead_path, allow_fixture=True)


def test_gfs_production_evidence_binds_official_urls_to_product_identity(tmp_path):
    path = gfs_artifact(tmp_path)
    payload = json.loads(path.read_text())
    product_id = payload["source"]["product_id"]
    payload["source"].update({
        "source_uri": f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/{product_id}",
        "publication_evidence": f"https://www.nco.ncep.noaa.gov/pmb/products/wave/{product_id}.shtml",
    })
    payload["revision"] = artifact_revision(payload)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    assert load_artifact(path)["source"]["product_id"] == product_id

    payload["source"]["publication_evidence"] = "https://www.nco.ncep.noaa.gov/pmb/products/wave/unrelated.shtml"
    payload["revision"] = artifact_revision(payload)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ProviderError, match="invalid publication evidence"):
        load_artifact(path)


def test_provider_outages_remain_independent_and_never_zero_fill(tmp_path):
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime(fail_stations={"44099"})),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
    ).compose(request())
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].coverage == "unavailable" and by_role["observation"].points == []
    assert by_role["forecast"].coverage == "complete"
    assert by_role["independent_check"].availability.state == "live"

    exhausted = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime(fail_stations={"44099", "44014"})),
    ).compose(request())
    assert all(item.coverage == "unavailable" for item in exhausted.manifest.offshore_series)
    assert all(item.state == "unavailable" for item in exhausted.manifest.berth_exposure)


def test_stale_ndbc_is_unavailable_while_gfs_forecast_remains_available(tmp_path):
    later = AS_OF + timedelta(hours=4)
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
    ).compose(request(as_of_utc=later, horizon_start_utc=later))
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].coverage == "unavailable"
    assert "NDBC stale" in by_role["observation"].availability.reason
    assert by_role["forecast"].coverage == "complete"
    assert any("not relabeled as an observation" in item for item in response.manifest.limitations)


def test_stale_gfs_cycle_is_unavailable_even_when_its_rows_cover_the_horizon(tmp_path):
    stale_as_of = datetime(2026, 11, 6, 7, tzinfo=UTC)
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
    ).compose(request(
        as_of_utc=stale_as_of,
        horizon_start_utc=stale_as_of,
        horizon_end_utc=stale_as_of + timedelta(hours=1),
    ))
    forecast = next(item for item in response.manifest.offshore_series if item.role == "forecast")
    assert forecast.coverage == "unavailable"
    assert "GFS-Wave stale" in forecast.availability.reason


def test_wave_composition_total_deadline_skips_remaining_sources(tmp_path):
    ticks = iter([0.0, 25.0])
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
        monotonic=lambda: next(ticks),
    ).compose(request())
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].availability.state == "live"
    assert by_role["forecast"].coverage == "unavailable"
    assert by_role["independent_check"].coverage == "unavailable"
    assert "total deadline" in by_role["forecast"].availability.reason


def test_wave_source_applicability_is_rejected_for_an_unreviewed_berth():
    composer = WaveComposer(ndbc=NDBCStationAdapter(FixtureRealtime()))
    with pytest.raises(ProviderError, match="applicability is established only"):
        composer.compose(request(berth_id="NAVSTA-NORFOLK-P12-S"))


def test_observation_rows_cannot_predate_their_own_recorded_retrieval():
    response = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime(retrieved_at=datetime(2026, 11, 5, 16, 25, tzinfo=UTC))),
    ).compose(request())
    by_role = {item.role: item for item in response.manifest.offshore_series}
    assert by_role["observation"].coverage == "unavailable"
    assert "later than its recorded retrieval" in by_role["observation"].availability.reason
    assert by_role["independent_check"].availability.state == "live"


def test_http_route_returns_the_same_frozen_wave_revision(tmp_path):
    composer = WaveComposer(
        ndbc=NDBCStationAdapter(FixtureRealtime()),
        gfs_artifact_path=gfs_artifact(tmp_path),
        allow_fixture_artifact=True,
    )
    expected = composer.compose(request())
    waves.configure(composer)
    with TestClient(app) as client:
        result = client.post("/api/v1/env/waves/compose", json=request().model_dump(mode="json"))
    assert result.status_code == 200, result.text
    assert result.json() == expected.model_dump(mode="json")
