"""D2 composed forecast resolver with independent component failure states."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mooring import refdata
from mooring.core.schemas import (
    ComposedForecast,
    ComposedForecastManifest,
    ComposedForecastRequest,
    CurrentForecastPoint,
    EnvironmentComponentAvailability,
    EnvironmentComponentProvenance,
    EnvironmentMetadata,
    EnvironmentSnapshot,
    ForecastComponentSeries,
    WaterLevelForecastPoint,
    WindForecastPoint,
)

from . import coops
from .cbofs import M_TO_FT
from .cbofs_artifact import load_artifact
from .errors import ProviderError
from .forecast_hashing import component_content_sha256, manifest_revision
from .nws import NWSGridpoint


def _unavailable(component: str, reason: str, *, limitations: list[str] | None = None) -> ForecastComponentSeries:
    return ForecastComponentSeries(
        availability=EnvironmentComponentAvailability(
            component=component,
            state="unavailable",
            reason=reason,
            limitations=limitations or [],
        )
    )


def _bound_series(availability: EnvironmentComponentAvailability, points) -> ForecastComponentSeries:
    provisional = ForecastComponentSeries(
        availability=availability,
        content_sha256="0" * 64,
        points=points,
    )
    return provisional.model_copy(update={"content_sha256": component_content_sha256(provisional)})


def _grid(start: datetime, end: datetime, step_min: int) -> list[datetime]:
    step = timedelta(minutes=step_min)
    values, at = [], start
    while at < end:
        values.append(at)
        at += step
    values.append(end)
    return values


class ForecastComposer:
    """Compose NWS plus CO-OPS predictions, or an explicitly selected synthetic scenario."""

    def __init__(self, *, nws=None, coops_fetcher=None, clock=None, cbofs_artifact_path: Path | str | None = None):
        self.nws = nws or NWSGridpoint()
        self.coops_fetcher = coops_fetcher or coops.Fetcher()
        self.clock = clock or (lambda: datetime.now(UTC))
        configured_artifact = cbofs_artifact_path or os.getenv("MOORING_CBOFS_ARTIFACT")
        self.cbofs_artifact_path = Path(configured_artifact) if configured_artifact else None

    def compose(self, request: ComposedForecastRequest) -> ComposedForecast:
        berth = refdata.berth(request.berth_id)
        if request.source.mode == "scenario":
            return self._scenario(request)
        wind = self._wind(request, berth)
        cbofs_components, cbofs_reason = self._cbofs(request, berth)
        if cbofs_components is not None:
            current, water = cbofs_components
        else:
            current = self._current(request, berth)
            water = self._water_level(request, berth)
            if cbofs_reason:
                current = self._with_limitation(current, f"CBOFS not used: {cbofs_reason}")
                water = self._with_limitation(water, f"CBOFS not used: {cbofs_reason}")
        components = [wind, current, water]
        snapshots = self._public_snapshots(request, components)
        available = [item for item in components if item.availability.state == "prediction"]
        complete = self._complete(request, components, snapshots)
        status = "complete" if complete else "partial" if available else "unavailable"
        limitations = []
        if status != "complete":
            limitations.append(
                "No complete public forcing is claimed; missing components, gusts, coverage or cadence remain explicit."
            )
        manifest = ComposedForecastManifest(
            revision="sha256:" + "0" * 64,
            request=request,
            status=status,
            components=components,
            limitations=limitations,
        )
        manifest = manifest.model_copy(update={"revision": manifest_revision(manifest)})
        return ComposedForecast(manifest=manifest, snapshots=snapshots)

    @staticmethod
    def _with_limitation(series: ForecastComponentSeries, limitation: str) -> ForecastComponentSeries:
        availability = series.availability.model_copy(update={
            "limitations": [*series.availability.limitations, limitation],
        })
        if series.availability.state == "unavailable":
            return series.model_copy(update={"availability": availability})
        provisional = series.model_copy(update={"availability": availability, "content_sha256": "0" * 64})
        return provisional.model_copy(update={"content_sha256": component_content_sha256(provisional)})

    def _cbofs(self, request, berth):
        if self.cbofs_artifact_path is None:
            return None, None
        try:
            artifact = load_artifact(self.cbofs_artifact_path)
            target = artifact["request"]
            if (not math.isclose(float(target["latitude"]), berth.origin_lat, rel_tol=0, abs_tol=1e-6)
                    or not math.isclose(float(target["longitude"]), berth.origin_lon, rel_tol=0, abs_tol=1e-6)):
                raise ProviderError("no_data", "decoded artifact target does not match the requested berth coordinate")
            depth_ft = float(target["depth_m"]) * M_TO_FT
            if (not math.isclose(depth_ft, request.current_depth_ft, rel_tol=0, abs_tol=1e-6)
                    or str(target["layer_id"]) != request.current_bin):
                raise ProviderError("no_data", "decoded artifact depth/layer does not exactly match the request")
            source_meta = artifact["source"]
            issued = datetime.fromisoformat(source_meta["issued_at_utc"].replace("Z", "+00:00")).astimezone(UTC)
            retrieved = datetime.fromisoformat(source_meta["retrieved_at_utc"].replace("Z", "+00:00")).astimezone(UTC)
            if issued > request.as_of_utc:
                raise ProviderError("unavailable", "CBOFS verified publication was after as_of_utc")
            rows = [row for row in artifact["rows"]
                    if request.horizon_start_utc <= datetime.fromisoformat(
                        row["valid_at_utc"].replace("Z", "+00:00")
                    ).astimezone(UTC) <= request.horizon_end_utc]
            if not rows:
                raise ProviderError("no_data", "decoded artifact has no rows in the requested horizon")
            omitted = {
                datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
                for row in rows for value in row.get("omitted_times_utc", [])
            }
            if any(request.horizon_start_utc <= value <= request.horizon_end_utc for value in omitted):
                raise ProviderError("no_data", "decoded artifact declares an omitted time in the requested horizon")
            times = [datetime.fromisoformat(row["valid_at_utc"].replace("Z", "+00:00")).astimezone(UTC) for row in rows]
            if (times[0] != request.horizon_start_utc or times[-1] != request.horizon_end_utc
                    or any((b - a).total_seconds() > request.step_min * 60 for a, b in zip(times, times[1:]))):
                raise ProviderError("no_data", "decoded artifact does not cover the full requested horizon/cadence")
            if any(not math.isclose(float(row["depth_m"]), float(target["depth_m"]), rel_tol=0, abs_tol=1e-6)
                   for row in rows):
                raise ProviderError("malformed", "decoded artifact row depth conflicts with its request")
            current_points = [CurrentForecastPoint(
                valid_at_utc=at,
                current_speed_kt=row["current_speed_kt"],
                current_set_true_deg=row["current_set_true_deg"],
                original={"u_v_decoded_source": artifact["revision"]},
            ) for at, row in zip(times, rows)]
            water_points = [WaterLevelForecastPoint(
                valid_at_utc=at,
                water_level_mllw_ft=row["water_level_mllw_ft"],
                original={"zetatomllw_decoded_source": artifact["revision"]},
            ) for at, row in zip(times, rows)]
            grid_cell = f"{float(rows[0]['grid_latitude']):.6f},{float(rows[0]['grid_longitude']):.6f}"
            source = f"NOAA CBOFS regular grid {source_meta['uri']}"
            limitations = [*artifact.get("limitations", []), source_meta["publication_evidence"]]
            current = _bound_series(EnvironmentComponentAvailability(
                component="current",
                state="prediction",
                source=source,
                basis="prediction",
                issued_at_utc=issued,
                retrieved_at_utc=retrieved,
                valid_from_utc=times[0],
                valid_to_utc=times[-1],
                quality="unknown",
                grid_cell=grid_cell,
                current_depth_ft=request.current_depth_ft,
                current_bin=request.current_bin,
                limitations=limitations,
            ), current_points)
            water = _bound_series(EnvironmentComponentAvailability(
                component="water_level",
                state="prediction",
                source=source,
                basis="prediction",
                issued_at_utc=issued,
                retrieved_at_utc=retrieved,
                valid_from_utc=times[0],
                valid_to_utc=times[-1],
                quality="unknown",
                grid_cell=grid_cell,
                vertical_datum="MLLW",
                limitations=limitations,
            ), water_points)
            return (current, water), None
        except (KeyError, TypeError, ValueError, ProviderError) as exc:
            return None, str(exc)

    def _wind(self, request, berth) -> ForecastComponentSeries:
        hours = math.ceil((request.horizon_end_utc - request.as_of_utc).total_seconds() / 3600)
        try:
            rows = self.nws.forecast(
                berth.origin_lat,
                berth.origin_lon,
                as_of=request.as_of_utc,
                hours=hours,
            )
            rows = [
                row for row in rows
                if row.valid_to_utc >= request.horizon_start_utc
                and row.valid_from_utc <= request.horizon_end_utc
            ]
            if not rows:
                raise ProviderError("no_data", "NWS has no wind periods in the requested horizon")
            if any(row.stale for row in rows):
                raise ProviderError("stale", "NWS response came from stale provider cache")
            points = [WindForecastPoint(
                valid_from_utc=max(row.valid_from_utc, request.horizon_start_utc),
                valid_to_utc=min(row.valid_to_utc, request.horizon_end_utc),
                wind_speed_kt=row.speed_kt,
                wind_gust_kt=row.gust_kt,
                wind_from_true_deg=row.from_true_deg,
                original=row.original,
            ) for row in rows if max(row.valid_from_utc, request.horizon_start_utc) < min(row.valid_to_utc, request.horizon_end_utc)]
            if not points:
                raise ProviderError("no_data", "NWS periods do not overlap the requested horizon")
            issued = max(row.issued_at_utc for row in rows)
            source = ", ".join(sorted({row.source for row in rows}))
            availability = EnvironmentComponentAvailability(
                component="wind",
                state="prediction",
                source=source,
                basis="prediction",
                issued_at_utc=issued,
                valid_from_utc=points[0].valid_from_utc,
                valid_to_utc=points[-1].valid_to_utc,
                quality="unknown",
                grid_cell=source.removeprefix("NWS "),
                wind_averaging_s=None,
                gust_duration_s=None,
                limitations=[
                    "NWS grid wind is not a berth measurement.",
                    "Wind averaging and gust duration are not documented; missing gusts stay null.",
                ],
            )
            return _bound_series(availability, points)
        except ProviderError as exc:
            return _unavailable("wind", f"NWS {exc.kind}: {exc}")
        except (TypeError, ValueError) as exc:
            return _unavailable("wind", f"NWS malformed: {exc}")

    def _retrieved_at(self, fetched) -> datetime:
        retrieved = getattr(fetched, "retrieved_at_utc", None)
        if retrieved is None:
            raise ProviderError("unavailable", "provider response has no recorded retrieval completion")
        return retrieved.astimezone(UTC)

    def _current(self, request, berth) -> ForecastComponentSeries:
        station = berth.env_station_ids.current
        try:
            requested_bin = int(request.current_bin)
        except ValueError:
            return _unavailable("current", f"CO-OPS current bin {request.current_bin!r} is not numeric")
        try:
            fetched = self.coops_fetcher.get(coops.request_params(
                "currents_predictions",
                station,
                request.horizon_start_utc,
                request.horizon_end_utc,
                bin=requested_bin,
            ))
            if fetched.stale:
                raise ProviderError("stale", "CO-OPS current prediction response came from stale cache")
            retrieved = self._retrieved_at(fetched)
            if retrieved > request.as_of_utc:
                raise ProviderError(
                    "unavailable",
                    f"current predictions were retrieved {retrieved.isoformat()} after as_of_utc",
                )
            rows = [row for row in coops.parse_current_predictions(fetched.doc)
                    if request.horizon_start_utc <= row["t"] <= request.horizon_end_utc]
            usable = [row for row in rows if row["current_speed_kt"] is not None and row["current_set_true_deg"] is not None]
            if not usable:
                raise ProviderError("no_data", "CO-OPS returned no usable current predictions in the requested horizon")
            if any(str(row["bin"]) != request.current_bin or row["depth_ft"] != request.current_depth_ft for row in usable):
                raise ProviderError(
                    "no_data",
                    "CO-OPS current prediction depth/bin differs from the explicit request; no nearby layer is substituted",
                )
            points = [CurrentForecastPoint(
                valid_at_utc=row["t"],
                current_speed_kt=row["current_speed_kt"],
                current_set_true_deg=row["current_set_true_deg"] % 360,
                original={
                    "speed_kt": row["current_speed_kt"],
                    "direction_deg": row["current_set_true_deg"],
                    "depth_ft": row["depth_ft"],
                    "bin": str(row["bin"]),
                },
            ) for row in usable]
            availability = EnvironmentComponentAvailability(
                component="current",
                state="prediction",
                source=f"NOAA CO-OPS {station} currents_predictions bin {request.current_bin}",
                basis="prediction",
                retrieved_at_utc=retrieved,
                valid_from_utc=points[0].valid_at_utc,
                valid_to_utc=points[-1].valid_at_utc,
                quality="unknown",
                station_id=station,
                current_depth_ft=request.current_depth_ft,
                current_bin=request.current_bin,
                limitations=[
                    "Retrieval establishes available-by time, not provider issuance or forecast freshness.",
                    "Station-bin guidance is not a qualified pier-wide or vessel-draft current profile.",
                ],
            )
            return _bound_series(availability, points)
        except ProviderError as exc:
            return _unavailable(
                "current",
                f"CO-OPS {exc.kind}: {exc}",
                limitations=["No current depth/bin substitution is permitted."],
            )
        except (TypeError, ValueError) as exc:
            return _unavailable(
                "current",
                f"CO-OPS malformed: {exc}",
                limitations=["No current depth/bin substitution is permitted."],
            )

    def _water_level(self, request, berth) -> ForecastComponentSeries:
        station = berth.env_station_ids.water_level
        try:
            fetched = self.coops_fetcher.get(coops.request_params(
                "predictions",
                station,
                request.horizon_start_utc,
                request.horizon_end_utc,
                datum="MLLW",
            ))
            if fetched.stale:
                raise ProviderError("stale", "CO-OPS water-level prediction response came from stale cache")
            retrieved = self._retrieved_at(fetched)
            if retrieved > request.as_of_utc:
                raise ProviderError(
                    "unavailable",
                    f"water-level predictions were retrieved {retrieved.isoformat()} after as_of_utc",
                )
            rows = [row for row in coops.parse_predictions(fetched.doc)
                    if request.horizon_start_utc <= row["t"] <= request.horizon_end_utc
                    and row["water_level_ft"] is not None]
            if not rows:
                raise ProviderError("no_data", "CO-OPS returned no usable MLLW predictions in the requested horizon")
            points = [WaterLevelForecastPoint(
                valid_at_utc=row["t"],
                water_level_mllw_ft=row["water_level_ft"],
                original={"water_level_ft_mllw": row["water_level_ft"]},
            ) for row in rows]
            availability = EnvironmentComponentAvailability(
                component="water_level",
                state="prediction",
                source=f"NOAA CO-OPS {station} water_level predictions",
                basis="prediction",
                retrieved_at_utc=retrieved,
                valid_from_utc=points[0].valid_at_utc,
                valid_to_utc=points[-1].valid_at_utc,
                quality="unknown",
                station_id=station,
                vertical_datum="MLLW",
                limitations=["Retrieval establishes available-by time, not provider issuance or forecast freshness."],
            )
            return _bound_series(availability, points)
        except ProviderError as exc:
            return _unavailable("water_level", f"CO-OPS {exc.kind}: {exc}")
        except (TypeError, ValueError) as exc:
            return _unavailable("water_level", f"CO-OPS malformed: {exc}")

    @staticmethod
    def _public_snapshots(request, components) -> list[EnvironmentSnapshot]:
        by_name = {item.availability.component: item for item in components}
        if any(by_name[name].availability.state != "prediction" for name in ("wind", "current", "water_level")):
            return []
        currents = {point.valid_at_utc.astimezone(UTC): point for point in by_name["current"].points}
        levels = {point.valid_at_utc.astimezone(UTC): point for point in by_name["water_level"].points}
        times = sorted(set(currents).intersection(levels))
        rows = []
        for at in times:
            if not request.horizon_start_utc <= at <= request.horizon_end_utc:
                continue
            wind = max(
                (point for point in by_name["wind"].points
                 if point.valid_from_utc.astimezone(UTC) <= at <= point.valid_to_utc.astimezone(UTC)),
                key=lambda point: point.valid_from_utc,
                default=None,
            )
            if wind is None or wind.wind_gust_kt is None:
                continue
            rows.append((at, wind, currents[at], levels[at]))
        snapshots = []
        for index, (at, wind, current, level) in enumerate(rows):
            valid_to = rows[index + 1][0] if index + 1 < len(rows) else at
            provenance = []
            for component, series in by_name.items():
                availability = series.availability
                point_valid_from = wind.valid_from_utc if component == "wind" else at
                point_valid_to = min(wind.valid_to_utc, valid_to) if component == "wind" else valid_to
                provenance.append(EnvironmentComponentProvenance(
                    component=component,
                    source=availability.source,
                    basis="prediction",
                    issued_at_utc=availability.issued_at_utc,
                    retrieved_at_utc=availability.retrieved_at_utc,
                    valid_from_utc=point_valid_from,
                    valid_to_utc=point_valid_to,
                    quality=availability.quality,
                    limitations=availability.limitations,
                ))
            snapshots.append(EnvironmentSnapshot(
                valid_at_utc=at,
                source="forecast",
                wind_speed_kt=wind.wind_speed_kt,
                wind_gust_kt=wind.wind_gust_kt,
                wind_from_true_deg=wind.wind_from_true_deg,
                current_speed_kt=current.current_speed_kt,
                current_set_true_deg=current.current_set_true_deg,
                water_level_mllw_ft=level.water_level_mllw_ft,
                metadata=EnvironmentMetadata(
                    basis="prediction",
                    source="Composed NWS and NOAA CO-OPS public forecast",
                    components=provenance,
                    valid_from_utc=at,
                    valid_to_utc=valid_to,
                    wind_averaging_s=None,
                    gust_duration_s=None,
                    current_depth_ft=request.current_depth_ft,
                    current_bin=request.current_bin,
                    vertical_datum="MLLW",
                    quality="unknown",
                ),
            ))
        return snapshots

    @staticmethod
    def _complete(request, components, snapshots) -> bool:
        if not snapshots or any(item.availability.state != "prediction" for item in components):
            return False
        times = [snapshot.valid_at_utc.astimezone(UTC) for snapshot in snapshots]
        if times[0] != request.horizon_start_utc or times[-1] != request.horizon_end_utc:
            return False
        if any((b - a).total_seconds() > request.step_min * 60 for a, b in zip(times, times[1:])):
            return False
        for index, snapshot in enumerate(snapshots):
            required_until = times[index + 1] if index + 1 < len(times) else request.horizon_end_utc
            if any(item.valid_to_utc is None or item.valid_to_utc.astimezone(UTC) < required_until
                   for item in snapshot.metadata.components):
                return False
        return True

    def _scenario(self, request) -> ComposedForecast:
        from mooring import environment

        scenario = environment.get_scenario(request.source.env_scenario_id)
        if scenario.kind == "replay" and scenario.replay_source == "recorded_real":
            raise ProviderError("invalid_request", "recorded observations cannot be promoted to an advance forecast")
        times = _grid(request.horizon_start_utc, request.horizon_end_utc, request.step_min)
        try:
            raw = [environment.scenario_snapshot(scenario.env_scenario_id, at, request.berth_id) for at in times]
        except ProviderError as exc:
            unavailable = [_unavailable(name, f"scenario {exc.kind}: {exc}")
                           for name in ("wind", "current", "water_level")]
            manifest = ComposedForecastManifest(
                revision="sha256:" + "0" * 64,
                request=request,
                status="unavailable",
                components=unavailable,
                limitations=["The selected scenario does not cover the requested horizon and was not looped."],
            )
            manifest = manifest.model_copy(update={"revision": manifest_revision(manifest)})
            return ComposedForecast(manifest=manifest, snapshots=[])

        snapshots = []
        wind_points, current_points, water_points = [], [], []
        for index, (at, snapshot) in enumerate(zip(times, raw)):
            valid_to = times[index + 1] if index + 1 < len(times) else at
            component_rows = [EnvironmentComponentProvenance(
                component=name,
                source=f"Explicit environment scenario {scenario.env_scenario_id}",
                basis="scenario",
                valid_from_utc=at,
                valid_to_utc=valid_to,
                quality="unknown",
                limitations=["Synthetic scenario forcing; not a public forecast."],
            ) for name in ("wind", "current", "water_level")]
            snapshots.append(snapshot.model_copy(update={
                "source": "scenario",
                "metadata": EnvironmentMetadata(
                    basis="scenario",
                    source=f"Explicit environment scenario {scenario.env_scenario_id}",
                    components=component_rows,
                    valid_from_utc=at,
                    valid_to_utc=valid_to,
                    current_depth_ft=request.current_depth_ft,
                    current_bin=request.current_bin,
                    vertical_datum="MLLW",
                    quality="unknown",
                ),
            }))
            if index + 1 < len(times):
                wind_points.append(WindForecastPoint(
                    valid_from_utc=at,
                    valid_to_utc=valid_to,
                    wind_speed_kt=snapshot.wind_speed_kt,
                    wind_gust_kt=snapshot.wind_gust_kt,
                    wind_from_true_deg=snapshot.wind_from_true_deg,
                ))
            current_points.append(CurrentForecastPoint(
                valid_at_utc=at,
                current_speed_kt=snapshot.current_speed_kt,
                current_set_true_deg=snapshot.current_set_true_deg,
            ))
            water_points.append(WaterLevelForecastPoint(
                valid_at_utc=at,
                water_level_mllw_ft=snapshot.water_level_mllw_ft,
            ))
        common = dict(
            state="mock",
            source=f"Explicit environment scenario {scenario.env_scenario_id}",
            basis="scenario",
            valid_from_utc=times[0],
            valid_to_utc=times[-1],
            quality="unknown",
            limitations=["Synthetic scenario forcing; not a public forecast."],
        )
        components = [
            _bound_series(EnvironmentComponentAvailability(component="wind", **common), wind_points),
            _bound_series(EnvironmentComponentAvailability(
                component="current", current_depth_ft=request.current_depth_ft,
                current_bin=request.current_bin, **common,
            ), current_points),
            _bound_series(EnvironmentComponentAvailability(
                component="water_level", vertical_datum="MLLW", **common,
            ), water_points),
        ]
        manifest = ComposedForecastManifest(
            revision="sha256:" + "0" * 64,
            request=request,
            status="complete",
            components=components,
            limitations=["Explicit synthetic scenario; not public forecast guidance."],
        )
        manifest = manifest.model_copy(update={"revision": manifest_revision(manifest)})
        return ComposedForecast(manifest=manifest, snapshots=snapshots)


_COMPOSER: ForecastComposer | None = None


def configure(composer: ForecastComposer | None = None) -> None:
    global _COMPOSER
    _COMPOSER = composer


def compose(request: ComposedForecastRequest) -> ComposedForecast:
    global _COMPOSER
    if _COMPOSER is None:
        _COMPOSER = ForecastComposer()
    return _COMPOSER.compose(request)
