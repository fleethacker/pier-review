"""Opt-in live smoke check of the CO-OPS adapter (not run by tests or CI; needs network).

    uv run --all-packages python scripts/smoke_coops.py

For every berth's configured stations it fetches the latest hour of wind, water level and currents through the real adapter and
prints what is available, the station bins and product coverage. A failure here means the provider or station configuration
changed; it does not indicate a software defect on its own. Exit status 1 if anything required is unavailable."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modeling"))

from mooring import refdata  # noqa: E402
from mooring.environment import coops  # noqa: E402
from mooring.environment.replay import ReplaySource  # noqa: E402


def main() -> int:
    f = coops.Fetcher(timeout_s=20.0, retries=2, backoff_s=2.0, min_interval_s=0.6)
    c = coops.Coops(f)
    end = datetime.now(UTC)
    bad = 0
    for b in refdata.berths():
        s = b.env_station_ids
        try:
            recs, notes, stale = c.window(s.wind, s.water_level, s.current, end - timedelta(hours=3), end)
            src = ReplaySource(recs, source_kind="live", max_gap_s=900, stale_after_s=1800)
            cov = src.coverage
            print(f"{b.berth_id}: {len(recs)} joined records, coverage {cov[0].isoformat() if cov else None}..{cov[1].isoformat() if cov else None}, "
                  f"{len(notes)} dropped, stale={stale}")
            if not recs:
                bad += 1
        except coops.ProviderError as e:
            print(f"{b.berth_id}: {e.kind}: {e}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
