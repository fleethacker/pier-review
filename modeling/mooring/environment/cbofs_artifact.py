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
import subprocess
import sys
import tempfile
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


def _memory_limit(max_memory_mb: int) -> None:
    """Use a kernel address-space cap, or checked peak RSS on macOS.

    macOS aliases RLIMIT_AS to the unsupported RLIMIT_RSS. Its worker is
    additionally supervised by the parent, which terminates it on RSS excess.
    The peak check catches allocations between parent polls before publication.
    """
    try:
        import resource
    except ImportError as exc:
        raise RuntimeError("this platform cannot enforce the configured CBOFS memory limit") from exc
    limit = max_memory_mb * 1024 * 1024
    if sys.platform == "darwin":
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > limit:
            raise ProviderError("unavailable", "CBOFS worker exceeded its resident-memory limit")
    else:
        hard = resource.getrlimit(resource.RLIMIT_AS)[1]
        bounded = min(hard, limit) if hard > 0 else limit
        resource.setrlimit(resource.RLIMIT_AS, (bounded, bounded))


def _check_resident_memory(process, max_memory_mb: int, remaining: float) -> None:
    if sys.platform != "darwin":
        return
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
            capture_output=True, text=True, timeout=min(remaining, 0.5), check=False,
        )
        if result.returncode or not result.stdout.strip():
            if not process.is_alive():
                return
            raise ValueError("worker RSS is unavailable")
        if int(result.stdout.strip()) * 1024 > max_memory_mb * 1024 * 1024:
            raise ProviderError("unavailable", "CBOFS worker exceeded its resident-memory limit")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ProviderError("unavailable", f"CBOFS worker memory supervision failed: {exc}") from None


def _write_bounded_artifact(path: Path, payload: dict, max_artifact_bytes: int) -> None:
    size = 1  # final newline
    with path.open("wb") as stream:
        for part in json.JSONEncoder(sort_keys=True, separators=(",", ":")).iterencode(payload):
            encoded = part.encode()
            size += len(encoded)
            if size > max_artifact_bytes:
                raise ProviderError("unavailable", f"decoded CBOFS artifact exceeds {max_artifact_bytes} bytes")
            stream.write(encoded)
        stream.write(b"\n")


def _worker(result_queue, kwargs, max_memory_mb, artifact_path, max_artifact_bytes):
    try:
        _memory_limit(max_memory_mb)
        payload = decode_artifact(**kwargs)
        _write_bounded_artifact(artifact_path, payload, max_artifact_bytes)
        _memory_limit(max_memory_mb)
        # Only a small status crosses the pipe; decoded data stays in the bounded file.
        result_queue.put(("ok", ""))
    except Exception as exc:  # child reports a bounded message; parent owns policy
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"[:2000]))


def _close_worker(process, result_queue) -> None:
    if process.pid is not None:
        if process.is_alive():
            process.terminate()
        process.join(0.5)
        if process.is_alive():
            process.kill()
            process.join(0.5)
        if not process.is_alive():
            process.close()
    result_queue.close()
    result_queue.join_thread()


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
    """Spawn bounded attempts and atomically publish one decoded cache artifact.

    Linux uses an address-space limit. macOS uses supervised resident memory,
    sampled at most every 50 ms plus bounded process-inspection time, and checks
    worker peak RSS before publishing. Allocations can overshoot between samples.
    Deadline cleanup may take one extra second.
    """
    if (not math.isfinite(total_timeout_s) or total_timeout_s <= 0 or type(retries) is not int or retries < 0
            or type(max_artifact_bytes) is not int or max_artifact_bytes <= 0
            or type(max_memory_mb) is not int or max_memory_mb <= 0):
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
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temporary_dir:
        temporary = Path(temporary_dir) / "decoded.json"
        for _ in range(retries + 1):
            if time.monotonic() >= deadline:
                break
            result_queue = context.Queue(maxsize=1)
            process = context.Process(
                target=_worker,
                args=(result_queue, kwargs, max_memory_mb, temporary, max_artifact_bytes),
                daemon=True,
            )
            try:
                process.start()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderError("unavailable", "CBOFS total acquisition deadline exceeded")
                    _check_resident_memory(process, max_memory_mb, remaining)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderError("unavailable", "CBOFS total acquisition deadline exceeded")
                    try:
                        # Drain before joining: Queue producers wait for their feeder to flush on exit.
                        state, message = result_queue.get(timeout=min(0.05, remaining))
                        break
                    except queue.Empty:
                        if not process.is_alive():
                            raise ProviderError("unavailable", f"CBOFS worker exited {process.exitcode} without a result")
                if state != "ok":
                    last_error = message
                    continue
                payload = load_artifact(temporary, max_artifact_bytes=max_artifact_bytes)
                if time.monotonic() >= deadline:
                    raise ProviderError("unavailable", "CBOFS total acquisition deadline exceeded")
                os.replace(temporary, output)
                return payload
            except ProviderError as exc:
                last_error = str(exc)
            finally:
                _close_worker(process, result_queue)
    raise ProviderError("unavailable", f"CBOFS acquisition failed: {last_error}")


def load_artifact(path: Path, *, max_artifact_bytes: int = 1_000_000) -> dict:
    try:
        with path.open("rb") as stream:
            data = stream.read(max_artifact_bytes + 1)
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
