"""Acquire one decoded CBOFS cache artifact in a bounded child process."""

import argparse
from datetime import datetime
from pathlib import Path

from mooring.environment.cbofs_artifact import acquire_artifact


def aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except ValueError:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601 and include a timezone") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Local NetCDF file or approved NOAA HTTPS CBOFS URL")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument("--depth-m", required=True, type=float)
    parser.add_argument("--layer-id", required=True)
    parser.add_argument("--issued-at-utc", required=True, type=aware,
                        help="Verified actual provider publication time, not cycle initialization")
    parser.add_argument("--retrieved-at-utc", required=True, type=aware)
    parser.add_argument("--publication-evidence", required=True)
    parser.add_argument("--total-timeout-s", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--max-artifact-bytes", type=int, default=1_000_000)
    parser.add_argument("--max-memory-mb", type=int, default=2048,
                        help="Worker memory cap: kernel address space on Linux; supervised/peak RSS on macOS")
    args = parser.parse_args()
    artifact = acquire_artifact(
        args.output,
        source=args.source,
        latitude=args.latitude,
        longitude=args.longitude,
        depth_m=args.depth_m,
        layer_id=args.layer_id,
        issued_at_utc=args.issued_at_utc,
        retrieved_at_utc=args.retrieved_at_utc,
        publication_evidence=args.publication_evidence,
        total_timeout_s=args.total_timeout_s,
        retries=args.retries,
        max_artifact_bytes=args.max_artifact_bytes,
        max_memory_mb=args.max_memory_mb,
    )
    print(f"wrote {args.output} revision {artifact['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
