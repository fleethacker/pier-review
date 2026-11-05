"""Offline synthetic regression inputs for the historical fitting tool; no observed data or qualification claim."""

import importlib.util
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec = importlib.util.spec_from_file_location("fit_uncertainty_script", Path(__file__).parents[2] / "scripts/fit_uncertainty.py")
fit_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit_tool)


def fixture():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    args = SimpleNamespace(start=start, end=start + timedelta(days=400), name="synthetic-test", wind="wind-test", current="current-test", bin=4)
    wind, current, predictions = [], [], []
    for day in range(20):
        for i in range(30):
            t = start + timedelta(days=day, minutes=i * 6)
            speed = 10 + math.sin(i * 0.7) + math.cos(i * 0.19)
            wind.append({"t": t, "quality": "good", "wind_speed_kt": speed,
                         "wind_gust_kt": speed * (1.15 + 0.08 * math.sin(i * 0.4)), "wind_from_true_deg": 10 + math.sin(i) * 5})
            current.append({"t": t, "quality": "good", "current_speed_kt": 0.8 + 0.1 * math.sin(i)})
            predictions.append({"t": t, "current_speed_kt": 0.8})
    return wind, current, predictions, args


def test_fit_uses_observed_days_and_training_only_parameters():
    wind, current, predictions, args = fixture()
    baseline = fit_tool.fit(wind, current, predictions, args)
    assert baseline.n_days == 20 and baseline.n_events == 20
    assert baseline.qualification == "unqualified"
    held_start = args.start + timedelta(days=14)
    altered_wind = [{**r, "wind_from_true_deg": r["wind_from_true_deg"] + 130,
                     "wind_speed_kt": r["wind_speed_kt"] * 2, "wind_gust_kt": r["wind_gust_kt"] * 3}
                    if r["t"] >= held_start else r for r in wind]
    altered_current = [{**r, "current_speed_kt": r["current_speed_kt"] + 3} if r["t"] >= held_start else r for r in current]
    changed = fit_tool.fit(altered_wind, altered_current, predictions, args)
    for field in ("gust_factor_mu", "gust_factor_sigma", "direction_sigma_deg", "current_sigma_kt", "correlation_time_min", "sectors"):
        assert getattr(changed, field) == getattr(baseline, field)
    assert changed.validation.observed_coverage != baseline.validation.observed_coverage


def test_fit_missing_current_is_not_zero_uncertainty():
    wind, _, predictions, args = fixture()
    with pytest.raises(ValueError, match="missing uncertainty is not zero"):
        fit_tool.fit(wind, [], predictions, args)


def test_fit_duplicate_rows_do_not_inflate_counts_or_parameters():
    wind, current, predictions, args = fixture()
    baseline = fit_tool.fit(wind, current, predictions, args)
    duplicate = fit_tool.fit(wind * 2, current * 2, predictions * 2, args)
    assert baseline == duplicate
    with pytest.raises(ValueError, match="conflicting observations"):
        fit_tool.fit([*wind, {**wind[0], "wind_speed_kt": 40}], current, predictions, args)


def test_fit_requires_aware_times_and_excludes_outside_window():
    wind, _, _, args = fixture()
    with pytest.raises(ValueError, match="timezone-aware"):
        fit_tool._window_rows([{**wind[0], "t": wind[0]["t"].replace(tzinfo=None)}], args.start, args.end)
    assert fit_tool._window_rows([{**wind[0], "t": args.end}], args.start, args.end) == []


def test_fetch_cache_separates_stations_and_does_not_cache_failure(tmp_path, monkeypatch):
    _, _, _, args = fixture()
    args.end = args.start + timedelta(days=1)
    args.cache = str(tmp_path)
    calls = []
    failing = [True]
    class Fetcher:
        def __init__(self, **kwargs):
            pass
        def get(self, params):
            calls.append(params)
            if failing[0]:
                raise fit_tool.coops.ProviderError("unavailable", "synthetic provider failure")
            return SimpleNamespace(doc=params)
    monkeypatch.setattr(fit_tool.coops, "Fetcher", Fetcher)
    for parser in ("parse_wind", "parse_currents", "parse_current_predictions"):
        monkeypatch.setattr(fit_tool.coops, parser, lambda doc: [{"t": args.start, "station": doc["station"]}])
    assert fit_tool.fetch(args) == ([], [], [])
    assert list(tmp_path.iterdir()) == []
    failing[0] = False
    first = fit_tool.fetch(args)
    assert len(calls) == 6
    assert fit_tool.fetch(args) == first and len(calls) == 6
    args.wind = "different-wind"
    changed = fit_tool.fetch(args)
    assert len(calls) == 7 and changed[0][0]["station"] == "different-wind"
    args.bin = 5
    fit_tool.fetch(args)
    assert len(calls) == 10



def test_current_prediction_join_uses_actual_nearest_time():
    wind, current, predictions, args = fixture()
    baseline = fit_tool.fit(wind, current, predictions, args)
    shifted = [{**r, "t": r["t"] + timedelta(minutes=1)} for r in predictions]
    assert fit_tool.fit(wind, current, shifted, args).current_sigma_kt == pytest.approx(baseline.current_sigma_kt)
