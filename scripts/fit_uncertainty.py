"""Fit the stochastic environment model (S10) from CO-OPS observations and write a compact artifact.

Opt-in, needs network; not run by tests or CI. Usage:
    uv run --all-packages python scripts/fit_uncertainty.py --wind 8638614 --level 8638610 --current cb0402 \
        --start 2025-01-01 --end 2025-12-31 --cache /path/to/cache --out modeling/mooring/environment/models/NAME.json

What is fitted (observations only; forecast error is NOT fitted from observations and is not modeled):
  * gust factor g/s (wind speed s >= 5 kt, clean flags) as a lognormal;
  * wind-direction scatter: circular std of 6-min directions about the circular mean of each hour (s >= 5 kt);
  * current-speed residual: observed minus predicted speed at the same bin (needs predictions);
  * correlation time: AR(1) of 6-min wind-speed deviations from their centered 1-hour mean.
Independent events are UTC days with at least 20 usable samples. Fitting and validation are split by event (the latest 30 %
of days are held out whole); held-out coverage of the nominal 90 % gust-factor interval is recorded; `qualify()` then applies
the minimum-data policy. The artifact stores parameters and provenance only, never the observations.
"""

import argparse
import json
import math
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modeling"))

from mooring.core.schemas import UncertaintyModel  # noqa: E402
from mooring.environment import coops, uncertainty as unc  # noqa: E402


def months(start: datetime, end: datetime, days: int = 30):
    t = start
    while t < end:
        yield t, min(t + timedelta(days=days), end)
        t += timedelta(days=days)


def fetch(args):
    f = coops.Fetcher(timeout_s=30.0, retries=3, backoff_s=2.0, min_interval_s=0.6, cache_ttl_s=10**9)
    c = coops.Coops(f)
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    wind, current, level, cpred = [], [], [], []
    for b, e in months(args.start, args.end):
        tag = b.strftime("%Y%m%d")
        for name, call in (("wind", lambda: coops.parse_wind(f.get(coops.request_params("wind", args.wind, b, e)).doc)),
                           ("cur", lambda: coops.parse_currents(f.get(coops.request_params("currents", args.current, b, e, bin=args.bin)).doc)),
                           ("cpred", lambda: coops.parse_current_predictions(f.get(coops.request_params("currents_predictions", args.current, b, e, bin=args.bin)).doc))):
            path = cache / f"{name}_{tag}.json"
            if path.exists():
                rows = json.loads(path.read_text())
                for r in rows:
                    r["t"] = datetime.fromisoformat(r["t"])
            else:
                try:
                    rows = call()
                except coops.ProviderError as err:
                    print(f"  {name} {tag}: {err}", file=sys.stderr)
                    rows = []
                path.write_text(json.dumps([{**r, "t": r["t"].isoformat()} for r in rows]))
            {"wind": wind, "cur": current, "cpred": cpred}[name].extend(rows)
        print(f"fetched {tag}", file=sys.stderr)
    return wind, current, cpred


def fit(wind, current, cpred, args) -> UncertaintyModel:
    good = [r for r in wind if r["quality"] == "good" and None not in (r["wind_speed_kt"], r["wind_gust_kt"], r["wind_from_true_deg"]) and r["wind_speed_kt"] >= 5.0
            and r["wind_gust_kt"] >= r["wind_speed_kt"]]
    by_day: dict[str, list] = {}
    for r in good:
        by_day.setdefault(r["t"].date().isoformat(), []).append(r)
    days = {d: v for d, v in by_day.items() if len(v) >= 20}
    items = [(r["t"], d, r["wind_gust_kt"] / r["wind_speed_kt"]) for d, v in days.items() for r in v]
    fit_gf, held_gf = unc.split_by_event(items, 0.3)
    mu, sigma = unc.fit_lognormal(fit_gf)
    # direction scatter about each hour's circular mean
    devs = []
    hours: dict[str, list] = {}
    for r in good:
        hours.setdefault(r["t"].strftime("%Y%m%d%H"), []).append(r["wind_from_true_deg"])
    for h, ds in hours.items():
        if len(ds) >= 8:
            m = unc.circular_mean_deg(ds)
            devs += [unc.angle_diff_deg(d, m) for d in ds]
    dir_sigma = math.sqrt(sum(x * x for x in devs) / len(devs))
    # current residual (observed - predicted) joined by nearest time
    pred = sorted(cpred, key=lambda r: r["t"])
    res = []
    idx = {r["t"]: r for r in pred}
    for r in current:
        if r["current_speed_kt"] is None:
            continue
        for dt in (0, -120, 120, -240, 240, -360, 360):
            p = idx.get(r["t"] + timedelta(seconds=dt))
            if p and p["current_speed_kt"] is not None:
                res.append(r["current_speed_kt"] - p["current_speed_kt"])
                break
    cur_sigma = statistics.pstdev(res) if len(res) > 100 else 0.0
    # turbulence correlation time from deviations about the centered 1-hour mean
    series = sorted(good, key=lambda r: r["t"])
    dev = []
    for i in range(5, len(series) - 5):
        w = series[i - 5: i + 6]
        if (w[-1]["t"] - w[0]["t"]) <= timedelta(minutes=66):
            dev.append(series[i]["wind_speed_kt"] - statistics.fmean(x["wind_speed_kt"] for x in w))
    phi, _, tau = unc.fit_ar1(dev, 6.0)
    model = UncertaintyModel(
        model_id=args.name, revision="1", kind="fitted", station_ids=[args.wind, args.current], fit_start_utc=args.start, fit_end_utc=args.end,
        filters=["wind speed >= 5 kt", "wind flags clean (X, R = 0)", "gust >= sustained", "UTC days with >= 20 usable samples count as events",
                 "current residual: observed minus predicted, nearest sample within 6 min"],
        gust_factor_mu=mu, gust_factor_sigma=sigma, direction_sigma_deg=dir_sigma, current_sigma_kt=cur_sigma, correlation_time_min=tau,
        n_events=len(days), n_days=(args.end - args.start).total_seconds() / 86400.0, validation=unc.coverage(
            UncertaintyModel(model_id="tmp", revision="0", kind="fitted", gust_factor_mu=mu, gust_factor_sigma=sigma, direction_sigma_deg=1, current_sigma_kt=0,
                             correlation_time_min=1, n_events=0, n_days=0, qualification="unqualified"), held_gf, 0.9),
        applicability=[f"Wind at CO-OPS {args.wind} and current at {args.current} bin {args.bin}, {args.start.date()} to {args.end.date()}, wind >= 5 kt."],
        limitations=["Observations only: forecast error and tide error are not fitted.", "Direction scatter is within-hour variability, not forecast direction error.",
                     "No storm or hurricane winds in the data window.", "Gust factor is truncated at gust >= sustained and fitted for wind >= 5 kt."],
        qualification="unqualified")
    print(f"gust-factor samples fit {len(fit_gf)} held {len(held_gf)}; direction samples {len(devs)}; current residuals {len(res)}; AR phi {phi:.3f}", file=sys.stderr)
    return unc.qualify(model)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wind", required=True); ap.add_argument("--level", required=True); ap.add_argument("--current", required=True)
    ap.add_argument("--bin", type=int, default=4); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--cache", required=True); ap.add_argument("--out", required=True); ap.add_argument("--name", default=None)
    a = ap.parse_args()
    a.start = datetime.fromisoformat(a.start).replace(tzinfo=UTC)
    a.end = datetime.fromisoformat(a.end).replace(tzinfo=UTC)
    a.name = a.name or f"coops-{a.wind}-{a.start.year}"
    model = fit(*fetch(a), a)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(model.model_dump_json(indent=1) + "\n")
    print(json.dumps({"model": a.name, "qualification": model.qualification, "reasons": model.qualification_reasons}, indent=1))


if __name__ == "__main__":
    main()
