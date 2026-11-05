"""Build the small manifest-backed NOAA CO-OPS replay package used by D1.

The input files are the checked-in provider responses. No network access is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mooring.environment import coops
from mooring.environment.providers import canonical_fixture_bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modeling/mooring/environment/fixtures/coops"
PACKAGE = (
    ROOT
    / "modeling/mooring/environment/fixtures/recorded_real"
    / "noaa-coops-norfolk-2026-01-01-v1"
)
SOURCE_COMMIT = "2518d8e76a340074957fbd0b9c425de71618af7c"


def _load(name: str) -> dict:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_time(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _alignment_bounds(value: str) -> dict[str, str]:
    observed = datetime.fromisoformat(_valid_time(value).replace("Z", "+00:00"))
    tolerance = timedelta(seconds=coops.ALIGN_TOLERANCE_S)
    return {
        "valid_from_utc": (observed - tolerance).isoformat().replace("+00:00", "Z"),
        "valid_to_utc": (observed + tolerance).isoformat().replace("+00:00", "Z"),
    }


ALIGNMENT_NOTE = (
    f"Nearest-observation replay alignment is limited to +/-{coops.ALIGN_TOLERANCE_S:g} seconds; "
    "these are alignment bounds, not provider-declared validity or simultaneous measurements. "
    "Exact observation times remain in metadata.original (wind_t, current_t, level_t)."
)


def render() -> dict[Path, bytes]:
    names = {
        "wind": "wind_8638614.json",
        "water_level": "water_level_8638610.json",
        "current": "currents_cb0402_bin4.json",
    }
    wind = coops.parse_wind(_load(names["wind"]))
    level = coops.parse_water_level(_load(names["water_level"]))
    current = coops.parse_currents(_load(names["current"]))
    records, notes = coops.assemble(
        wind,
        level,
        current,
        wind_station="8638614",
        level_station="8638610",
        current_station="cb0402",
        bin=4,
        bin_depth_ft=20.6,
    )
    for record in records:
        original = record["original"]
        record["components"] = [
            {
                "basis": "observation",
                "component": "wind",
                "limitations": ["wind averaging and gust duration are not documented by this response", ALIGNMENT_NOTE],
                "quality": record["quality"],
                "source": "NOAA CO-OPS station 8638614",
                **_alignment_bounds(original["wind_t"]),
            },
            {
                "basis": "observation",
                "component": "current",
                "limitations": [
                    "current direction is treated as toward and remains pending authoritative confirmation",
                    "bin 4 depth is approximately 20.6 ft below the surface and may not apply at every vessel draft",
                    ALIGNMENT_NOTE,
                ],
                "quality": record["quality"],
                "source": "NOAA CO-OPS station cb0402 bin 4",
                **_alignment_bounds(original["current_t"]),
            },
            {
                "basis": "observation",
                "component": "water_level",
                "limitations": [ALIGNMENT_NOTE],
                "quality": record["quality"],
                "source": "NOAA CO-OPS station 8638610, MLLW",
                **_alignment_bounds(original["level_t"]),
            },
        ]

    observations = canonical_fixture_bytes(records)
    start, end = records[0]["t"], records[-1]["t"]
    source_files = []
    for component, name in names.items():
        data = (SOURCE / name).read_bytes()
        source_files.append({
            "component": component,
            "path": f"../../coops/{name}",
            "sha256": _sha(data),
        })
    manifest = {
        "acquisition": {
            "acquisition_date": "2026-11-04",
            "retrieved_at_utc": None,
            "retrieval_time_note": "Exact retrieval time was not recorded; acquisition date comes from the introducing commit.",
            "source_commit": SOURCE_COMMIT,
        },
        "applicable_berth_ids": ["NAVSTA-NORFOLK-P12-N", "NAVSTA-NORFOLK-P12-S"],
        "attribution": {
            "credit": "National Oceanic and Atmospheric Administration (NOAA) CO-OPS",
            "legal_review": "not independently reviewed",
            "terms_url": "https://oceanservice.noaa.gov/about/disclaimer.html",
        },
        "coverage": {
            "end_utc": end,
            "join_tolerance_s": coops.ALIGN_TOLERANCE_S,
            "max_interpolation_gap_s": 900,
            "nominal_cadence_s": 360,
            "record_count": len(records),
            "start_utc": start,
        },
        "data": {
            "path": "observations.json",
            "sha256": _sha(observations),
        },
        "kind": "recorded_observation",
        "limitations": [
            "Recorded observations are demonstration replay data, not a forecast or operational qualification.",
            "Wind averaging and gust duration are undocumented.",
            "Current direction convention remains pending authoritative confirmation.",
            "Current is from cb0402 bin 4 at an assumed depth of 20.6 ft below the surface.",
            "The three stations are spatially separated and representativeness at the berth is unqualified.",
            ALIGNMENT_NOTE,
            *notes,
        ],
        "normalization": [
            "English-unit CO-OPS values are retained as knots, degrees true and feet MLLW.",
            "Records are joined on wind timestamps with the declared tolerance.",
            "Component validity intervals describe that bounded alignment; original observation times are retained separately.",
            "No value is extrapolated, looped or synthesized.",
        ],
        "package_id": "noaa-coops-norfolk-2026-01-01-v1",
        "schema_version": "recorded-replay-v1",
        "source_files": source_files,
        "stations": [
            {"component": "wind", "product": "wind", "station_id": "8638614", "units": "knots/degrees true"},
            {"component": "current", "product": "currents", "station_id": "cb0402", "bin": "4", "depth_ft": 20.6, "units": "knots/degrees true"},
            {"component": "water_level", "product": "water_level", "station_id": "8638610", "datum": "MLLW", "units": "feet"},
        ],
    }
    # The revision binds behavior-critical applicability, provenance and policy
    # metadata as well as the separately hashed observation/source files.
    manifest["revision"] = f"sha256:{_sha(canonical_fixture_bytes(manifest))}"
    return {
        PACKAGE / "observations.json": observations,
        PACKAGE / "manifest.json": canonical_fixture_bytes(manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, data in render().items():
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if stale:
        print("Recorded replay package is stale:\n  " + "\n  ".join(stale))
        return 1
    print("recorded replay package up to date" if args.check else "recorded replay package written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
