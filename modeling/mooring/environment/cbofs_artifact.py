"""Bounded CBOFS acquisition process and verified decoded-artifact reader.

API workers read only the small JSON artifact. Native NetCDF access stays in the
spawned acquisition process whose main thread owns and closes the dataset.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import queue
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from .cbofs import CBOFSSampler, open_subset
from .errors import ProviderError
from .forecast_hashing import canonical_bytes

SCHEMA_VERSION = "cbofs-decoded-v1"


def _time(value: str | datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (AttributeError, TypeError, ValueError):
        raise ProviderError("malformed", f"invalid CBOFS artifact timestamp {value!r}") from None


def _revision(payload: dict) -> str:
    bound = dict(payload)
    bound.pop("revision", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(bound)).hexdigest()


def _valid_publication_evidence(value: str, source: str) -> bool:
    value = value.strip()
    if value.startswith("fixture:"):
        return not urlsplit(source).scheme
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"opendap.co-ops.nos.noaa.gov", "tidesandcurrents.noaa.gov"}
        and not parsed.username
        and not parsed.password
    )


def decode_artifact(
    source: str,
    *,
    latitude: float,
    longitude: float,
    depth_m: float,
    layer_id: str,
    issued_at_utc: datetime,
    retrieved_at_utc: datetime,
    publication_evidence: str,
) -> dict:
    """Decode one source in the current process; intended for the child worker."""
    issued, retrieved = _time(issued_at_utc), _time(retrieved_at_utc)
    if issued > retrieved:
        raise ProviderError("malformed", "verified CBOFS issue time is after retrieval")
    if not _valid_publication_evidence(publication_evidence, source):
        raise ProviderError(
            "invalid_request",
            "CBOFS publication evidence must be an approved NOAA HTTPS reference (or fixture: for a local test source)",
        )
    with open_subset(source) as dataset:
        rows = CBOFSSampler().sample(
            dataset,
            latitude,
            longitude,
            depth_m=depth_m,
            issued_at=issued,
            as_of=retrieved,
        )
    data = [{
        "valid_at_utc": row.valid_at_utc.isoformat().replace("+00:00", "Z"),
        "current_speed_kt": row.current_speed_kt,
        "current_set_true_deg": row.current_toward_true_deg,
        "water_level_mllw_ft": row.water_level_mllw_ft,
        "depth_m": row.depth_m,
        "grid_latitude": row.grid_latitude,
        "grid_longitude": row.grid_longitude,
        "omitted_times_utc": [value.isoformat().replace("+00:00", "Z") for value in row.omitted_times_utc],
    } for row in rows]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "uri": source,
            "issued_at_utc": issued.isoformat().replace("+00:00", "Z"),
            "retrieved_at_utc": retrieved.isoformat().replace("+00:00", "Z"),
            "publication_evidence": publication_evidence,
        },
        "request": {
            "latitude": latitude,
            "longitude": longitude,
            "depth_m": depth_m,
            "layer_id": layer_id,
        },
        "rows": data,
        "limitations": list(rows[0].limitations),
    }
    payload["revision"] = _revision(payload)
    return payload


def _worker(result_queue, kwargs, max_memory_mb):
    try:
        if max_memory_mb:
            try:
                import resource
            except ImportError as exc:
                raise RuntimeError("this platform cannot enforce the configured CBOFS memory limit") from exc
            limit = int(max_memory_mb * 1024 * 1024)
            hard = resource.getrlimit(resource.RLIMIT_AS)[1]
            bounded = min(hard, limit) if hard > 0 else limit
            resource.setrlimit(resource.RLIMIT_AS, (bounded, bounded))
        payload = decode_artifact(**kwargs)
        result_queue.put(("ok", json.dumps(payload, sort_keys=True, separators=(",", ":"))))
    except Exception as exc:  # child reports a bounded message; parent owns policy
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"[:2000]))


def acquire_artifact(
    output: Path,
    *,
    source: str,
    latitude: float,
    longitude: float,
    depth_m: float,
    layer_id: str,
    issued_at_utc: datetime,
    retrieved_at_utc: datetime,
    publication_evidence: str,
    total_timeout_s: float = 30.0,
    retries: int = 0,
    max_artifact_bytes: int = 1_000_000,
    max_memory_mb: int = 2048,
) -> dict:
    """Spawn bounded attempts and atomically publish one decoded cache artifact."""
    if (not math.isfinite(total_timeout_s) or total_timeout_s <= 0 or type(retries) is not int or retries < 0
            or max_artifact_bytes <= 0 or max_memory_mb <= 0):
        raise ValueError("CBOFS acquisition bounds must be positive and retries a non-negative integer")
    kwargs = dict(
        source=source,
        latitude=latitude,
        longitude=longitude,
        depth_m=depth_m,
        layer_id=layer_id,
        issued_at_utc=issued_at_utc,
        retrieved_at_utc=retrieved_at_utc,
        publication_evidence=publication_evidence,
    )
    deadline = time.monotonic() + total_timeout_s
    last_error = "no acquisition attempt"
    context = multiprocessing.get_context("spawn")
    for _ in range(retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result_queue = context.Queue(maxsize=1)
        process = context.Process(target=_worker, args=(result_queue, kwargs, max_memory_mb), daemon=True)
        process.start()
        process.join(remaining)
        if process.is_alive():
            process.terminate()
            process.join(2)
            last_error = "total acquisition deadline exceeded"
            break
        try:
            state, message = result_queue.get(timeout=min(1.0, max(deadline - time.monotonic(), 0.01)))
        except queue.Empty:
            last_error = f"worker exited {process.exitcode} without a result"
            continue
        if state != "ok":
            last_error = message
            continue
        encoded = (message + "\n").encode()
        if len(encoded) > max_artifact_bytes:
            raise ProviderError("unavailable", f"decoded CBOFS artifact exceeds {max_artifact_bytes} bytes")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, output)
        return load_artifact(output, max_artifact_bytes=max_artifact_bytes)
    raise ProviderError("unavailable", f"CBOFS acquisition failed: {last_error}")


def load_artifact(path: Path, *, max_artifact_bytes: int = 1_000_000) -> dict:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProviderError("unavailable", f"CBOFS decoded artifact is unreadable: {exc}") from None
    if len(data) > max_artifact_bytes:
        raise ProviderError("unavailable", f"CBOFS decoded artifact exceeds {max_artifact_bytes} bytes")
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        raise ProviderError("malformed", "CBOFS decoded artifact is not valid JSON") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ProviderError("malformed", "CBOFS decoded artifact has an unsupported schema")
    if payload.get("revision") != _revision(payload):
        raise ProviderError("malformed", "CBOFS decoded artifact revision mismatch")
    source, request, rows = payload.get("source"), payload.get("request"), payload.get("rows")
    if not isinstance(source, dict) or not isinstance(request, dict) or not isinstance(rows, list) or not rows:
        raise ProviderError("malformed", "CBOFS decoded artifact is missing source, request or rows")
    try:
        latitude = float(request["latitude"])
        longitude = float(request["longitude"])
        depth_m = float(request["depth_m"])
        layer_id = request["layer_id"]
    except (KeyError, TypeError, ValueError):
        raise ProviderError("malformed", "CBOFS decoded artifact request is malformed") from None
    if (not all(math.isfinite(value) for value in (latitude, longitude, depth_m))
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or depth_m < 0
            or not isinstance(layer_id, str) or not layer_id):
        raise ProviderError("malformed", "CBOFS decoded artifact request has invalid coordinates/depth/layer")
    issued, retrieved = _time(source.get("issued_at_utc")), _time(source.get("retrieved_at_utc"))
    if (issued > retrieved
            or not _valid_publication_evidence(str(source.get("publication_evidence", "")), str(source.get("uri", "")))):
        raise ProviderError("malformed", "CBOFS decoded artifact has invalid publication provenance")
    previous = None
    for row in rows:
        try:
            at = _time(row["valid_at_utc"])
            numbers = [float(row[name]) for name in (
                "current_speed_kt", "current_set_true_deg", "water_level_mllw_ft",
                "depth_m", "grid_latitude", "grid_longitude",
            )]
        except (KeyError, TypeError, ValueError):
            raise ProviderError("malformed", "CBOFS decoded artifact row is malformed") from None
        if (any(not math.isfinite(value) for value in numbers) or numbers[0] < 0
                or not 0 <= numbers[1] < 360 or not -90 <= numbers[4] <= 90 or not -180 <= numbers[5] <= 180):
            raise ProviderError("malformed", "CBOFS decoded artifact row contains invalid values")
        if previous is not None and at <= previous:
            raise ProviderError("malformed", "CBOFS decoded artifact times are not strictly increasing")
        previous = at
        omitted = row.get("omitted_times_utc", [])
        if not isinstance(omitted, list):
            raise ProviderError("malformed", "CBOFS omitted_times_utc must be a list")
        for value in omitted:
            _time(value)
    return payload
