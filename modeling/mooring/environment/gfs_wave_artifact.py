"""Validated decoded GFS-Wave cache artifacts for API-safe forecast composition."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ProviderError
from .forecast_hashing import canonical_bytes

SCHEMA_VERSION = "gfs-wave-decoded-v1"
MODEL_ID = "gfs-wave"
GRID_ID = "atlocn.0p16"
GRID_RESOLUTION_DEG = 0.16
MAX_FORECAST_LEAD = timedelta(hours=384)
_PRODUCT_ID = re.compile(
    r"gfswave\.t(?P<cycle>00|06|12|18)z\.atlocn\.0p16(?:\.[A-Za-z0-9._-]+)?$"
)


def _time(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (AttributeError, TypeError, ValueError):
        raise ProviderError("malformed", f"invalid GFS-Wave artifact timestamp {value!r}") from None


def artifact_revision(payload: dict) -> str:
    bound = dict(payload)
    bound.pop("revision", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(bound)).hexdigest()


def _valid_evidence(source_uri: str, evidence: str, product_id: str, *, allow_fixture: bool) -> bool:
    if evidence.startswith("fixture:"):
        return allow_fixture and not urlsplit(source_uri).scheme
    try:
        source = urlsplit(source_uri)
        proof = urlsplit(evidence)
    except ValueError:
        return False
    return (
        source.scheme == proof.scheme == "https"
        and source.hostname == "nomads.ncep.noaa.gov"
        and proof.hostname == "www.nco.ncep.noaa.gov"
        and not source.username
        and not source.password
        and not proof.username
        and not proof.password
        and product_id in source_uri
        and product_id in evidence
        and proof.path.startswith("/pmb/products/wave/")
    )


def _finite(value, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ProviderError("malformed", f"GFS-Wave {name} is not numeric") from None
    if not math.isfinite(result):
        raise ProviderError("malformed", f"GFS-Wave {name} is not finite")
    return result


def _validate_component(
    component: dict,
    *,
    name: str,
    variables: tuple[str, str, str],
    partition: bool = False,
) -> None:
    if not isinstance(component, dict):
        raise ProviderError("malformed", f"GFS-Wave {name} component is not an object")
    height = _finite(component.get("significant_height_m"), name=f"{name} height")
    if height < 0:
        raise ProviderError("malformed", f"GFS-Wave {name} height is negative")
    height_variable, period_variable, direction_variable = variables
    if component.get("height_variable") != height_variable:
        raise ProviderError("malformed", f"GFS-Wave {name} height must come from {height_variable}")
    for field, variable_field, expected_variable in (
        ("period_s", "period_variable", period_variable),
        ("direction_from_true_deg", "direction_variable", direction_variable),
    ):
        if component.get(field) is None:
            if component.get(variable_field) is not None:
                raise ProviderError("malformed", f"GFS-Wave {name} {variable_field} has no value")
            continue
        if component.get(variable_field) != expected_variable:
            raise ProviderError("malformed", f"GFS-Wave {name} {field} must come from {expected_variable}")
        value = _finite(component[field], name=f"{name} {field}")
        if field == "period_s" and value <= 0:
            raise ProviderError("malformed", f"GFS-Wave {name} period must be positive")
        if field == "direction_from_true_deg" and not 0 <= value < 360:
            raise ProviderError("malformed", f"GFS-Wave {name} direction is outside [0, 360)")
    if partition and (not isinstance(component.get("partition_id"), str) or not component["partition_id"]):
        raise ProviderError("malformed", "GFS-Wave swell partition needs a partition_id")


def load_artifact(
    path: Path,
    *,
    max_artifact_bytes: int = 1_000_000,
    allow_fixture: bool = False,
) -> dict:
    if type(max_artifact_bytes) is not int or max_artifact_bytes <= 0:
        raise ValueError("max_artifact_bytes must be a positive integer")
    try:
        with path.open("rb") as stream:
            data = stream.read(max_artifact_bytes + 1)
    except OSError as exc:
        raise ProviderError("unavailable", f"GFS-Wave decoded artifact is unreadable: {exc}") from None
    if len(data) > max_artifact_bytes:
        raise ProviderError("unavailable", f"GFS-Wave artifact exceeds {max_artifact_bytes} bytes")
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        raise ProviderError("malformed", "GFS-Wave artifact is not valid JSON") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ProviderError("malformed", "GFS-Wave artifact has an unsupported schema")
    if payload.get("revision") != artifact_revision(payload):
        raise ProviderError("malformed", "GFS-Wave artifact revision mismatch")
    source, location, rows = payload.get("source"), payload.get("location"), payload.get("rows")
    if not isinstance(source, dict) or not isinstance(location, dict) or not isinstance(rows, list) or not rows:
        raise ProviderError("malformed", "GFS-Wave artifact is missing source, location or rows")
    if source.get("model_id") != MODEL_ID or source.get("grid_id") != GRID_ID:
        raise ProviderError("malformed", "GFS-Wave artifact has an unsupported model/grid identity")
    product_id = source.get("product_id")
    product_match = _PRODUCT_ID.fullmatch(product_id) if isinstance(product_id, str) else None
    if product_match is None:
        raise ProviderError("malformed", "GFS-Wave artifact is missing product_id")
    if not _valid_evidence(
        str(source.get("source_uri", "")),
        str(source.get("publication_evidence", "")),
        product_id,
        allow_fixture=allow_fixture,
    ):
        raise ProviderError("malformed", "GFS-Wave artifact has invalid publication evidence")
    reference = _time(source.get("reference_time_utc"))
    issued = _time(source.get("issued_at_utc"))
    retrieved = _time(source.get("retrieved_at_utc"))
    if not reference <= issued <= retrieved:
        raise ProviderError("malformed", "GFS-Wave reference, issue and retrieval times are inconsistent")
    if (
        reference.hour != int(product_match.group("cycle"))
        or reference.minute != 0
        or reference.second != 0
        or reference.microsecond != 0
    ):
        raise ProviderError("malformed", "GFS-Wave product cycle does not match reference_time_utc")
    latitude = _finite(location.get("latitude_deg"), name="grid latitude")
    longitude = _finite(location.get("longitude_deg"), name="grid longitude")
    grid_cell = location.get("grid_cell")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not isinstance(grid_cell, str) or not grid_cell:
        raise ProviderError("malformed", "GFS-Wave artifact has invalid grid-cell coordinates")
    if (
        abs(latitude / GRID_RESOLUTION_DEG - round(latitude / GRID_RESOLUTION_DEG)) > 1e-6
        or abs(longitude / GRID_RESOLUTION_DEG - round(longitude / GRID_RESOLUTION_DEG)) > 1e-6
    ):
        raise ProviderError("malformed", "GFS-Wave coordinates are not on the atlocn.0p16 grid lattice")
    expected_cell = f"{GRID_ID}:{latitude:.2f},{longitude:.2f}"
    if grid_cell != expected_cell:
        raise ProviderError("malformed", f"GFS-Wave grid_cell must bind its coordinates as {expected_cell}")

    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderError("malformed", "GFS-Wave artifact row is not an object")
        at = _time(row.get("valid_at_utc"))
        if at < reference or at > reference + MAX_FORECAST_LEAD:
            raise ProviderError("malformed", "GFS-Wave row is outside the official FH000-FH384 lead range")
        if previous is not None and at <= previous:
            raise ProviderError("malformed", "GFS-Wave row times precede reference or are not strictly increasing")
        previous = at
        total = row.get("total_sea")
        wind = row.get("wind_sea")
        swells = row.get("swell_partitions", [])
        if total is None and wind is None and not swells:
            raise ProviderError("malformed", "GFS-Wave row has no wave representation")
        if total is not None:
            _validate_component(total, name="total sea", variables=("HTSGW", "PERPW", "DIRPW"))
        if wind is not None:
            _validate_component(wind, name="wind sea", variables=("WVHGT", "WVPER", "WVDIR"))
        if not isinstance(swells, list):
            raise ProviderError("malformed", "GFS-Wave swell_partitions is not a list")
        ids = []
        levels = []
        for partition in swells:
            _validate_component(
                partition,
                name="swell",
                variables=("SWELL", "SWPER", "SWDIR"),
                partition=True,
            )
            level = partition.get("sequence_level")
            if type(level) is not int or not 1 <= level <= 3:
                raise ProviderError("malformed", "GFS-Wave swell needs native sequence_level 1, 2 or 3")
            if partition["partition_id"] != f"swell_{level}":
                raise ProviderError("malformed", "GFS-Wave swell partition_id must bind its native sequence level")
            ids.append(partition["partition_id"])
            levels.append(level)
        if len(ids) != len(set(ids)):
            raise ProviderError("malformed", "GFS-Wave swell partition identifiers are not unique")
        if levels != list(range(1, len(levels) + 1)):
            raise ProviderError("malformed", "GFS-Wave swell sequence levels must be ordered and contiguous")
    limitations = payload.get("limitations", [])
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        raise ProviderError("malformed", "GFS-Wave artifact limitations must be strings")
    return payload
