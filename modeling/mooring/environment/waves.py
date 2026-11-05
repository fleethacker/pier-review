"""D4 offshore wave composition with independent, explicit provider failures."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mooring import refdata
from mooring.core.schemas import (
    ComposedWaveManifest,
    ComposedWaves,
    EnvironmentComponentAvailability,
    OffshoreWavePoint,
    OffshoreWaveSeries,
    WaveBerthExposureAvailability,
    WaveBulkParameters,
    WaveComposeRequest,
    WaveSourceLocation,
)

from .errors import ProviderError
from .forecast_hashing import component_content_sha256, manifest_revision
from .gfs_wave_artifact import load_artifact
from .ndbc import M_TO_FT, STATIONS, NDBCStationAdapter

SUPPORTED_BERTH_ID = "NAVSTA-NORFOLK-P12-N"
APPROVED_GFS_GRID_CELL = "atlocn.0p16:36.96,-75.68"
APPROVED_GFS_LATITUDE_DEG = 36.96
APPROVED_GFS_LONGITUDE_DEG = -75.68
MAX_LIVE_OBSERVATION_AGE = timedelta(hours=3)
MAX_GFS_ISSUE_AGE = timedelta(hours=18)
MAX_COMPOSE_ELAPSED_S = 25.0


def _unavailable(role: str, *, station_id: str | None = None, reason: str) -> OffshoreWaveSeries:
    forecast = role == "forecast"
    return OffshoreWaveSeries(
        role=role,
        provider="gfs-wave" if forecast else "ndbc",
        station_id=station_id,
        model_id="gfs-wave" if forecast else None,
        coverage="unavailable",
        availability=EnvironmentComponentAvailability(
            component="waves",
            state="unavailable",
            source=(
                "NOAA/NCEP GFS-Wave"
                if forecast
                else f"NOAA/NDBC station {station_id}"
                + (" (operated by Scripps/CDIP)" if station_id == "44099" else "")
            ),
            basis="prediction" if forecast else "observation",
            quality="unknown",
            station_id=None if forecast else station_id,
            reason=reason,
        ),
    )


def _bind_series(**values) -> OffshoreWaveSeries:
    provisional = OffshoreWaveSeries.model_construct(content_sha256="0" * 64, **values)
    bound = provisional.model_copy(update={"content_sha256": component_content_sha256(provisional)})
    return OffshoreWaveSeries.model_validate(bound.model_dump(mode="json"))


def _component(raw: dict, *, component: str, partition_id: str | None = None) -> WaveBulkParameters:
    period = raw.get("period_s")
    direction = raw.get("direction_from_true_deg")
    partition = component != "total_sea"
    return WaveBulkParameters(
        component="provider_partition" if partition_id else component,
        provider_partition_id=partition_id,
        significant_height_ft=float(raw["significant_height_m"]) * M_TO_FT,
        period_s=period,
        period_basis=(
            "provider_partition_mean"
            if partition and period is not None
            else "primary_mean"
            if period is not None
            else "unknown"
        ),
        direction_from_true_deg=direction,
        direction_basis=(
            "provider_partition" if partition and direction is not None else "primary" if direction is not None else "unknown"
        ),
    )


class WaveComposer:
    def __init__(
        self,
        *,
        ndbc: NDBCStationAdapter | None = None,
        gfs_artifact_path: Path | str | None = None,
        allow_fixture_artifact: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.ndbc = ndbc or NDBCStationAdapter()
        configured = gfs_artifact_path or os.getenv("MOORING_GFS_WAVE_ARTIFACT")
        self.gfs_artifact_path = Path(configured) if configured else None
        self.allow_fixture_artifact = allow_fixture_artifact
        self.monotonic = monotonic

    def compose(self, request: WaveComposeRequest) -> ComposedWaves:
        started = self.monotonic()
        refdata.berth(request.berth_id)
        if request.berth_id != SUPPORTED_BERTH_ID:
            raise ProviderError(
                "invalid_request",
                f"wave-source applicability is established only for berth {SUPPORTED_BERTH_ID}",
            )
        observation = self._observation(request, request.observation_station_id, "observation", request.include_spectrum)
        if self.monotonic() - started >= MAX_COMPOSE_ELAPSED_S:
            forecast = _unavailable("forecast", reason="Wave composition total deadline reached before forecast loading.")
            independent = _unavailable(
                "independent_check",
                station_id=request.independent_check_station_id,
                reason="NDBC unavailable: wave composition total deadline reached",
            )
        else:
            forecast = self._forecast(request)
            if self.monotonic() - started >= MAX_COMPOSE_ELAPSED_S:
                independent = _unavailable(
                    "independent_check",
                    station_id=request.independent_check_station_id,
                    reason="NDBC unavailable: wave composition total deadline reached",
                )
            else:
                independent = self._observation(
                    request,
                    request.independent_check_station_id,
                    "independent_check",
                    False,
                )
                if self.monotonic() - started >= MAX_COMPOSE_ELAPSED_S:
                    independent = _unavailable(
                        "independent_check",
                        station_id=request.independent_check_station_id,
                        reason="NDBC unavailable: wave composition total deadline reached",
                    )
        limitations = [
            "Total sea, provider partitions and spectra are alternatives and must not be summed.",
            "NDBC and GFS-Wave values are offshore boundary conditions, not qualified berth forcing.",
            "Missing observations, model guidance, local chop and wakes remain unavailable rather than zero-filled.",
        ]
        if observation.coverage == "unavailable" and forecast.coverage != "unavailable":
            limitations.append(
                "NDBC 44099 is unavailable; GFS-Wave remains prediction guidance and is not relabeled as an observation."
            )
        exposures = [
            WaveBerthExposureAvailability(
                component="ocean_swell",
                reason_code="NO_BERTH_WAVE_TRANSFER",
                reason="No validated transformation from the offshore boundary to this berth.",
                limitations=["Offshore values cannot be copied into berth forcing."],
            ),
            WaveBerthExposureAvailability(
                component="local_chop",
                reason_code="NO_DIRECTIONAL_FETCH",
                reason="No reviewed directional fetch geometry is available for this berth.",
            ),
            WaveBerthExposureAvailability(
                component="ship_wake",
                reason_code="NO_WAKE_SOURCE",
                reason="No approved traffic feed and berth-validated ship-wake model are available.",
            ),
            WaveBerthExposureAvailability(
                component="tug_wake",
                reason_code="NO_WAKE_SOURCE",
                reason="No berth-validated tug-wake source or response model is available.",
            ),
        ]
        provisional = ComposedWaveManifest.model_construct(
            revision="sha256:" + "0" * 64,
            request=request,
            offshore_series=[observation, forecast, independent],
            berth_exposure=exposures,
            limitations=limitations,
        )
        bound = provisional.model_copy(update={"revision": manifest_revision(provisional)})
        return ComposedWaves(manifest=ComposedWaveManifest.model_validate(bound.model_dump(mode="json")))

    def _observation(self, request, station_id: str, role: str, include_spectrum: bool) -> OffshoreWaveSeries:
        try:
            acquired = self.ndbc.acquire(
                station_id,
                as_of_utc=request.as_of_utc,
                lookback_hours=request.observation_lookback_hours,
                include_spectrum=include_spectrum,
            )
            points = list(acquired.points)
            starts = [(point.sample_start_utc or point.valid_at_utc).astimezone(UTC) for point in points]
            ends = [(point.sample_end_utc or point.valid_at_utc).astimezone(UTC) for point in points]
            latest = max(ends)
            age = request.as_of_utc - latest
            if age > MAX_LIVE_OBSERVATION_AGE:
                raise ProviderError(
                    "stale",
                    f"latest NDBC row is {age.total_seconds():.0f}s old; live limit is "
                    f"{MAX_LIVE_OBSERVATION_AGE.total_seconds():.0f}s",
                )
            source = f"NOAA/NDBC station {station_id} realtime wave products"
            if station_id == "44099":
                source += " (station operated by Scripps/CDIP)"
            availability = EnvironmentComponentAvailability(
                component="waves",
                state="live",
                source=source,
                basis="observation",
                age_s=(request.as_of_utc - latest).total_seconds(),
                age_basis="valid_time",
                retrieved_at_utc=acquired.retrieved_at_utc,
                valid_from_utc=min(starts),
                valid_to_utc=latest,
                quality="unknown",
                limitations=list(acquired.limitations),
                station_id=station_id,
            )
            location = STATIONS[station_id]
            return _bind_series(
                role=role,
                provider="ndbc",
                station_id=station_id,
                model_id=None,
                reference_time_utc=None,
                coverage="partial",
                availability=availability,
                product_ids=list(acquired.product_ids),
                location=WaveSourceLocation(**location),
                points=points,
            )
        except ProviderError as exc:
            return _unavailable(role, station_id=station_id, reason=f"NDBC {exc.kind}: {exc}")
        except (TypeError, ValueError) as exc:
            return _unavailable(role, station_id=station_id, reason=f"NDBC malformed: {exc}")

    def _forecast(self, request: WaveComposeRequest) -> OffshoreWaveSeries:
        if self.gfs_artifact_path is None:
            return _unavailable(
                "forecast",
                reason="No decoded GFS-Wave artifact is configured; model guidance was not replaced with fabricated waves.",
            )
        try:
            artifact = load_artifact(self.gfs_artifact_path, allow_fixture=self.allow_fixture_artifact)
            source = artifact["source"]
            retrieved = datetime.fromisoformat(source["retrieved_at_utc"].replace("Z", "+00:00")).astimezone(UTC)
            issued = datetime.fromisoformat(source["issued_at_utc"].replace("Z", "+00:00")).astimezone(UTC)
            reference = datetime.fromisoformat(source["reference_time_utc"].replace("Z", "+00:00")).astimezone(UTC)
            if retrieved > request.as_of_utc:
                raise ProviderError("unavailable", "decoded artifact was retrieved after request as_of_utc")
            issue_age = request.as_of_utc - issued
            if issue_age > MAX_GFS_ISSUE_AGE:
                raise ProviderError(
                    "stale",
                    f"decoded artifact issue is {issue_age.total_seconds():.0f}s old; prediction limit is "
                    f"{MAX_GFS_ISSUE_AGE.total_seconds():.0f}s",
                )
            rows = artifact["rows"]
            row_times = [datetime.fromisoformat(row["valid_at_utc"].replace("Z", "+00:00")).astimezone(UTC) for row in rows]
            inside = [index for index, at in enumerate(row_times) if request.horizon_start_utc <= at <= request.horizon_end_utc]
            if not inside:
                raise ProviderError("no_data", "decoded artifact has no point in the requested forecast horizon")
            first = max((index for index, at in enumerate(row_times) if at <= request.horizon_start_utc), default=inside[0])
            last = min((index for index, at in enumerate(row_times) if at >= request.horizon_end_utc), default=inside[-1])
            selected = list(zip(rows[first:last + 1], row_times[first:last + 1]))
            points = []
            for row, at in selected:
                partitions = [
                    _component(item, component="provider_partition", partition_id=item["partition_id"])
                    for item in row.get("swell_partitions", [])
                ]
                if row.get("wind_sea") is not None:
                    partitions.append(_component(row["wind_sea"], component="wind_sea"))
                original = {
                    "artifact_revision": artifact["revision"],
                    "product_id": source["product_id"],
                }
                for key in ("total_sea", "swell_partitions", "wind_sea"):
                    if row.get(key) is not None:
                        original[f"{key}_native"] = json.dumps(
                            row[key], sort_keys=True, separators=(",", ":")
                        )
                points.append(OffshoreWavePoint(
                    valid_at_utc=at,
                    timestamp_basis="instant",
                    total_sea=_component(row["total_sea"], component="total_sea") if row.get("total_sea") else None,
                    partitions=partitions,
                    original=original,
                ))
            times = [point.valid_at_utc.astimezone(UTC) for point in points]
            maximum_gap = timedelta(hours=request.max_forecast_gap_hours)
            complete = (
                times[0] <= request.horizon_start_utc
                and times[-1] >= request.horizon_end_utc
                and all(b - a <= maximum_gap for a, b in zip(times, times[1:]))
            )
            location = artifact["location"]
            if (
                location["grid_cell"] != APPROVED_GFS_GRID_CELL
                or float(location["latitude_deg"]) != APPROVED_GFS_LATITUDE_DEG
                or float(location["longitude_deg"]) != APPROVED_GFS_LONGITUDE_DEG
            ):
                raise ProviderError(
                    "unavailable",
                    f"decoded artifact is not the approved offshore target {APPROVED_GFS_GRID_CELL}",
                )
            limitations = [
                *artifact.get("limitations", []),
                source["publication_evidence"],
                "GFS-Wave grid guidance is not a berth measurement and has no validated harbor transfer.",
            ]
            availability = EnvironmentComponentAvailability(
                component="waves",
                state="prediction",
                source=f"NOAA/NCEP GFS-Wave {source['grid_id']}",
                basis="prediction",
                age_s=issue_age.total_seconds(),
                age_basis="issued_time",
                issued_at_utc=issued,
                retrieved_at_utc=retrieved,
                valid_from_utc=times[0],
                valid_to_utc=times[-1],
                quality="unknown",
                limitations=limitations,
                grid_cell=location["grid_cell"],
            )
            return _bind_series(
                role="forecast",
                provider="gfs-wave",
                station_id=None,
                model_id="gfs-wave",
                reference_time_utc=reference,
                coverage="complete" if complete else "partial",
                availability=availability,
                product_ids=[source["product_id"]],
                location=WaveSourceLocation(**location),
                points=points,
            )
        except ProviderError as exc:
            return _unavailable("forecast", reason=f"GFS-Wave {exc.kind}: {exc}")
        except (KeyError, TypeError, ValueError) as exc:
            return _unavailable("forecast", reason=f"GFS-Wave malformed: {exc}")


_configured: WaveComposer | None = None


def configure(composer: WaveComposer | None) -> None:
    global _configured
    _configured = composer


def compose(request: WaveComposeRequest) -> ComposedWaves:
    global _configured
    if _configured is None:
        _configured = WaveComposer()
    return _configured.compose(request)
