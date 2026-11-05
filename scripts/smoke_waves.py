#!/usr/bin/env python3
"""Opt-in live probe for the approved NOAA/NDBC offshore wave products."""

import json
import os

from mooring.environment.ndbc import NDBCRealtime, merge_spectral_products, parse_summary


def main() -> int:
    if os.getenv("MOORING_LIVE_SMOKE") != "1":
        print("skipped: set MOORING_LIVE_SMOKE=1")
        return 0
    realtime = NDBCRealtime()
    primary = realtime.fetch("44099", "spec")
    density = realtime.fetch("44099", "data_spec")
    check = realtime.fetch("44014", "spec")
    primary_points = parse_summary(primary.text)
    check_points = parse_summary(check.text)
    spectra = merge_spectral_products({"data_spec": density.text})
    result = {
        "observation_station": "44099",
        "observation_retrieved_at_utc": primary.retrieved_at_utc.isoformat(),
        "observation_latest_valid_at_utc": max(point.valid_at_utc for point in primary_points).isoformat(),
        "density_latest_valid_at_utc": max(spectra).isoformat(),
        "density_bin_count": spectra[max(spectra)][0].frequency_bin_count,
        "independent_station": "44014",
        "independent_latest_valid_at_utc": max(point.valid_at_utc for point in check_points).isoformat(),
        "applicability": "offshore_boundary_only",
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
