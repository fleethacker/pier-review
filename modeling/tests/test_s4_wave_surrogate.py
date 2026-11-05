"""S4: seeded synthetic wave surrogate. Statistics are checked against independent spectral/analytical values."""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from mooring.core.schemas.wave_surrogate import SYNTHETIC_LABEL, WaveSpectrumComponent, WaveSpectrumInput, WaveSurrogateRequest
from mooring.data_simulation import wave_surrogate as W

DUR, DT = 1200.0, 0.5


def total(hs=4.0, tp=10.0, gamma=3.3):
    return WaveSpectrumInput(kind="total", source="test", components=[WaveSpectrumComponent(label="total_sea", hs_ft=hs, peak_period_s=tp, gamma=gamma)])


def parts(swell=(3.0, 12.0), wind=(2.0, 5.0), reported=None):
    return WaveSpectrumInput(kind="partitions", source="test", reported_total_hs_ft=reported, components=[
        WaveSpectrumComponent(label="swell", hs_ft=swell[0], peak_period_s=swell[1]),
        WaveSpectrumComponent(label="wind_sea", hs_ft=wind[0], peak_period_s=wind[1])])


def gen(spec, seed=1, dur=DUR, dt=DT):
    return W.generate(WaveSurrogateRequest(seed=seed, duration_s=dur, dt_s=dt, spectrum=spec))


def test_labeled_synthetic_unqualified():
    r = gen(total())
    assert r.state == "synthetic" and r.qualified is False and r.label == SYNTHETIC_LABEL and "UNQUALIFIED" in r.label


def test_deterministic_by_seed_and_seed_changes_output():
    a, b, c = gen(total(), 7), gen(total(), 7), gen(total(), 8)
    assert a.series.elevation_ft == b.series.elevation_ft
    assert a.series.elevation_ft != c.series.elevation_ft


def test_record_variance_equals_spectrum_m0_and_realized_hs_matches_target():
    spec = total(hs=4.0, tp=10.0)
    r = gen(spec)
    x = np.array(r.series.elevation_ft)
    f, s = W.component_spectrum(spec.components[0], DUR, DT)
    m0, _ = W.spectral_moments(f, s, DUR)
    assert m0 == pytest.approx((4.0 / 4) ** 2, rel=1e-12)         # normalisation independent of the sampler
    assert np.var(x) == pytest.approx(m0, rel=1e-9)                # orthogonal grid: exact
    assert r.realized_hs_ft == pytest.approx(4.0, rel=1e-9) and r.target_hs_ft == 4.0


def test_gaussian_marginal_statistics_across_seeds():
    spec = total()
    pooled = np.concatenate([np.array(gen(spec, s).series.elevation_ft) for s in range(40)])
    z = (pooled - pooled.mean()) / pooled.std()
    assert abs(pooled.mean()) < 0.05 and abs(float(np.mean(z**3))) < 0.08 and float(np.mean(z**4)) == pytest.approx(3.0, abs=0.2)


def test_mean_zero_crossing_period_matches_spectral_moments():
    spec = total(tp=10.0)
    f, s = W.component_spectrum(spec.components[0], DUR, DT)
    m0, m2 = W.spectral_moments(f, s, DUR)
    tz_analytic = math.sqrt(m0 / m2)   # Rice
    tz = np.mean([gen(spec, k).mean_zero_crossing_period_s for k in range(30)])
    assert tz == pytest.approx(tz_analytic, rel=0.08)


def test_peak_of_periodogram_is_near_requested_peak_frequency():
    for tp in (6.0, 10.0, 14.0):
        r = gen(total(tp=tp), 3)
        x = np.array(r.series.elevation_ft)
        p = np.abs(np.fft.rfft(x)) ** 2
        fpk = np.fft.rfftfreq(len(x), DT)[1:][np.argmax(p[1:])]
        assert fpk == pytest.approx(1.0 / tp, rel=0.25)  # random-phase periodogram is noisy; shape band is checked by the m0/Tz tests


def test_partitions_are_energy_additive_and_equal_the_equivalent_total_energy():
    r = gen(parts())
    x = np.array(r.series.elevation_ft)
    comps = {k: np.array(v) for k, v in r.series.components.items()}
    assert set(comps) == {"swell", "wind_sea"}
    assert np.var(comps["swell"]) == pytest.approx((3.0 / 4) ** 2, rel=1e-9) and np.var(comps["wind_sea"]) == pytest.approx((2.0 / 4) ** 2, rel=1e-9)
    assert np.allclose(x, comps["swell"] + comps["wind_sea"])  # each partition added exactly once
    assert r.target_hs_ft == pytest.approx(math.sqrt(3.0**2 + 2.0**2))
    # Random phases overlap on shared grid frequencies, so a single record only matches in expectation: average over seeds.
    mean_var = np.mean([np.var(np.array(gen(parts(), s).series.elevation_ft)) for s in range(60)])
    assert mean_var == pytest.approx((3.0**2 + 2.0**2) / 16.0, rel=0.03)


def test_reported_total_is_never_added_to_partitions():
    consistent = gen(parts(reported=math.sqrt(13.0)))
    inconsistent = gen(parts(reported=9.0))
    base = gen(parts())
    assert consistent.series.elevation_ft == base.series.elevation_ft == inconsistent.series.elevation_ft
    assert inconsistent.target_hs_ft == base.target_hs_ft
    assert any("NOT added" in n for n in inconsistent.notes) and not any("NOT added" in n for n in consistent.notes)


def test_total_plus_partitions_or_duplicates_are_rejected():
    c = WaveSpectrumComponent
    with pytest.raises(ValidationError):
        WaveSpectrumInput(kind="partitions", source="t", components=[c(label="total_sea", hs_ft=1, peak_period_s=8), c(label="swell", hs_ft=1, peak_period_s=8)])
    with pytest.raises(ValidationError):
        WaveSpectrumInput(kind="total", source="t", components=[c(label="total_sea", hs_ft=1, peak_period_s=8), c(label="swell", hs_ft=1, peak_period_s=8)])
    with pytest.raises(ValidationError):
        WaveSpectrumInput(kind="partitions", source="t", components=[c(label="swell", hs_ft=1, peak_period_s=8), c(label="swell", hs_ft=1, peak_period_s=9)])


def test_partition_phases_are_independent_of_other_partitions():
    both = gen(parts()).series.components["swell"]
    alone = gen(WaveSpectrumInput(kind="partitions", source="t", components=[WaveSpectrumComponent(label="swell", hs_ft=3.0, peak_period_s=12.0)])).series.components["swell"]
    assert both == alone


def test_zero_wave_input_reproduces_the_no_wave_baseline_exactly():
    base = [0.1 * i - 3.0 for i in range(int(DUR / DT))]
    r = gen(total(hs=0.0))
    assert r.state == "synthetic" and all(v == 0.0 for v in r.series.elevation_ft)
    out, applied = W.superpose(base, r)
    assert applied and out == base
    zero_parts, _ = W.superpose(base, gen(parts(swell=(0.0, 12.0), wind=(0.0, 5.0))))
    assert zero_parts == base


def test_missing_waves_are_unavailable_not_zero():
    r = gen(None)
    assert r.state == "unavailable" and r.series is None and r.realized_hs_ft is None and r.reasons
    base = [1.0, 2.0, 3.0]
    out, applied = W.superpose(base, r)
    assert out == base and applied is False


def test_unresolvable_period_is_unavailable_not_silently_truncated():
    r = gen(total(tp=0.8), dt=0.5)
    assert r.state == "unavailable" and "resolve" in r.reasons[0]
