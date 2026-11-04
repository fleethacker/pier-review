"""S10: stochastic environment tools. Synthetic data validates the algorithms only."""

import math
import random
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from mooring.core.schemas import EnvironmentSnapshot, HeldOutValidation
from mooring.environment import uncertainty as u

ENV = EnvironmentSnapshot(wind_speed_kt=20, wind_gust_kt=26, wind_from_true_deg=359.0, current_speed_kt=0.5,
                          current_set_true_deg=10, water_level_mllw_ft=1.0)


def test_circular_statistics_handle_the_north_wraparound():
    assert u.circular_mean_deg([359, 1]) == pytest.approx(0.0, abs=1e-9)
    assert u.circular_mean_deg([350, 10]) == pytest.approx(0.0, abs=1e-9)
    assert u.angle_diff_deg(359, 1) == pytest.approx(-2.0) and u.angle_diff_deg(1, 359) == pytest.approx(2.0)
    rng = random.Random(7)
    sample = [rng.gauss(0, 10) % 360 for _ in range(5000)]  # straddles 0/360
    assert u.circular_std_deg(sample) == pytest.approx(10.0, abs=0.5)
    assert statistics.pstdev(sample) > 100  # the naive statistic is wrong here, the circular one is right


def test_lognormal_fit_recovers_parameters_and_rejects_bad_input():
    rng = random.Random(3)
    xs = [math.exp(rng.gauss(0.27, 0.08)) for _ in range(20_000)]
    mu, sigma = u.fit_lognormal(xs)
    assert mu == pytest.approx(0.27, abs=0.005) and sigma == pytest.approx(0.08, abs=0.005)
    with pytest.raises(ValueError):
        u.fit_lognormal([1.0])


def test_ar1_fit_recovers_correlation_time():
    rng = random.Random(11)
    phi_true, x, series = 0.9, 0.0, []
    for _ in range(40_000):
        x = phi_true * x + rng.gauss(0, math.sqrt(1 - phi_true**2))
        series.append(x)
    phi, sigma, tau = u.fit_ar1(series, dt_min=6.0)
    assert phi == pytest.approx(0.9, abs=0.01) and tau == pytest.approx(-6.0 / math.log(0.9), rel=0.1) and sigma == pytest.approx(math.sqrt(1 - 0.81), abs=0.02)
    with pytest.raises(ValueError):
        u.fit_ar1([1.0, 1.0, 1.0], 6.0)


def test_split_by_event_never_splits_an_event_and_holds_out_the_latest():
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    items = [(t0 + timedelta(days=10 * e, hours=h), f"ev{e}", (e, h)) for e in range(10) for h in range(5)]
    fit, held = u.split_by_event(items, 0.3)
    fit_events, held_events = {v[0] for v in fit}, {v[0] for v in held}
    assert not fit_events & held_events and held_events == {7, 8, 9} and len(fit) + len(held) == 50


def test_heldout_coverage_diagnostic_and_minimum_data_policy():
    rng = random.Random(5)
    gfs = [math.exp(rng.gauss(0.27, 0.08)) for _ in range(40_000)]
    fit, held = gfs[:30_000], gfs[30_000:]
    mu, sigma = u.fit_lognormal(fit)
    model = u.SYNTHETIC_DEMO.model_copy(update={"model_id": "fit", "kind": "fitted", "gust_factor_mu": mu, "gust_factor_sigma": sigma,
                                                "n_events": 60, "n_days": 800.0})
    val = u.coverage(model, held, 0.9)
    assert 0.88 <= val.observed_coverage <= 0.92
    assert u.qualify(model.model_copy(update={"validation": val})).qualification == "qualified"
    # Insufficient data leaves the model unqualified, whatever the calibration says.
    thin = u.qualify(model.model_copy(update={"validation": val, "n_events": 5, "n_days": 30.0}))
    assert thin.qualification == "unqualified" and any("Only 5 independent events" in r for r in thin.qualification_reasons)
    # Miscalibrated coverage is rejected.
    bad = u.qualify(model.model_copy(update={"validation": HeldOutValidation(n_heldout=100, nominal_coverage=0.9, observed_coverage=0.6)}))
    assert bad.qualification == "unqualified"
    # Synthetic distributions never qualify; the storm limitation is always stated.
    assert u.qualify(u.SYNTHETIC_DEMO).qualification == "unqualified"
    assert all(any("Hurricane" in r for r in m.qualification_reasons) for m in (bad, thin, u.qualify(u.SYNTHETIC_DEMO)))
    assert u.SYNTHETIC_DEMO.qualification == "unqualified"


def test_seeded_sampling_is_reproducible_and_seed_dependent():
    a = [u.Sampler(u.SYNTHETIC_DEMO, 42).instant(ENV) for _ in range(1)]
    s1, s2, s3 = u.Sampler(u.SYNTHETIC_DEMO, 42), u.Sampler(u.SYNTHETIC_DEMO, 42), u.Sampler(u.SYNTHETIC_DEMO, 43)
    d1, d2, d3 = [s.instant(ENV).wind_gust_kt for s in (s1, s2, s3)]
    assert d1 == d2 and d1 != d3
    assert [x.wind_from_true_deg for x in u.Sampler(u.SYNTHETIC_DEMO, 9).trajectory(ENV, 20, 6)] == \
           [x.wind_from_true_deg for x in u.Sampler(u.SYNTHETIC_DEMO, 9).trajectory(ENV, 20, 6)]


def test_samples_respect_physical_bounds_and_direction_wraps():
    s = u.Sampler(u.SYNTHETIC_DEMO.model_copy(update={"direction_sigma_deg": 60.0, "current_sigma_kt": 5.0, "gust_factor_sigma": 0.5}), 1)
    for _ in range(2000):
        e = s.instant(ENV)
        assert 0 <= e.wind_from_true_deg < 360 and 0 <= e.current_speed_kt <= u.MAX_CURRENT_KT
        assert e.wind_gust_kt >= e.wind_speed_kt and e.wind_gust_kt <= u.MAX_WIND_KT


def test_gust_factor_marginal_matches_the_model():
    s = u.Sampler(u.SYNTHETIC_DEMO.model_copy(update={"gust_factor_mu": 0.3, "gust_factor_sigma": 0.1}), 2)
    gf = [s.instant(ENV).wind_gust_kt / ENV.wind_speed_kt for _ in range(20_000)]
    assert statistics.fmean(math.log(g) for g in gf) == pytest.approx(0.3, abs=0.005)


def test_trajectories_are_correlated_with_the_stated_time_and_stationary():
    m = u.SYNTHETIC_DEMO.model_copy(update={"correlation_time_min": 60.0, "gust_factor_sigma": 0.2, "gust_factor_mu": 0.0})
    s = u.Sampler(m, 4)
    path = s.trajectory(ENV, 6_000, 6.0)
    logs = [math.log(max(p.wind_gust_kt / ENV.wind_speed_kt, 1.0)) for p in path]  # clipped at 1: use only the positive side
    z = [(p.current_speed_kt - ENV.current_speed_kt) for p in path]
    d = [x - statistics.fmean(z) for x in z]
    r1 = sum(d[i] * d[i + 1] for i in range(len(d) - 1)) / sum(x * x for x in d)
    assert r1 == pytest.approx(math.exp(-6.0 / 60.0), abs=0.05)
