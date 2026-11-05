"""S4: seeded synthetic wave-forcing surrogate. Pure functions; deterministic by seed; always labeled unqualified.

Surface elevation at one point is a sum of harmonics on the frequency grid f_k = k / duration (orthogonal over the record,
so the record variance equals the discrete spectrum's m0 exactly). Amplitudes come from a JONSWAP-shaped spectrum
normalised so that Hs = 4 sqrt(m0) equals the supplied height; phases are uniform random from a per-component stream
`SeedSequence([seed, component_index])`, so adding or removing another component never changes this one's phases.
Total sea and partitions are alternatives: components are summed once, never a total plus its own partitions.
"""

import math

import numpy as np

from mooring.core.schemas.wave_surrogate import WaveSpectrumComponent, WaveSpectrumInput, WaveSurrogateRequest, WaveSurrogateResult, WaveSurrogateSeries

F_LOW, F_HIGH = 0.4, 4.0  # band as multiples of the peak frequency
PARTITION_TOTAL_TOLERANCE = 0.05


def jonswap_shape(f: np.ndarray, fp: float, gamma: float) -> np.ndarray:
    """Unnormalised JONSWAP shape (Hasselmann et al. 1973 form); the scale is fixed by the requested Hs."""
    sigma = np.where(f <= fp, 0.07, 0.09)
    r = np.exp(-((f - fp) ** 2) / (2 * sigma**2 * fp**2))
    return f**-5 * np.exp(-1.25 * (fp / f) ** 4) * gamma**r


def component_spectrum(c: WaveSpectrumComponent, duration_s: float, dt_s: float):
    """(frequencies, one-sided density) on the k/duration grid with m0 = (Hs/4)^2, or None if the band holds no grid points."""
    fp = 1.0 / c.peak_period_s
    fmax = min(F_HIGH * fp, 0.5 / dt_s * (1 - 1e-9))  # strictly below Nyquist so grid harmonics stay orthogonal on the sample grid
    k = np.arange(max(1, math.ceil(F_LOW * fp * duration_s)), math.floor(fmax * duration_s) + 1)
    if len(k) < 2:
        return None
    f = k / duration_s
    s = jonswap_shape(f, fp, c.gamma)
    df = 1.0 / duration_s
    m0 = float(np.sum(s) * df)
    return f, s * ((c.hs_ft / 4.0) ** 2 / m0)


def spectral_moments(f: np.ndarray, s: np.ndarray, duration_s: float) -> tuple[float, float]:
    df = 1.0 / duration_s
    return float(np.sum(s) * df), float(np.sum(s * f**2) * df)


def _component_series(c: WaveSpectrumComponent, t: np.ndarray, duration_s: float, dt_s: float, seed: int, index: int) -> np.ndarray:
    if c.hs_ft == 0.0:
        return np.zeros_like(t)
    spec = component_spectrum(c, duration_s, dt_s)
    if spec is None:
        raise ValueError(f"duration {duration_s:g} s is too short to resolve a {c.peak_period_s:g} s peak period")
    f, s = spec
    amp = np.sqrt(2.0 * s / duration_s)
    phase = np.random.default_rng(np.random.SeedSequence([seed, index])).uniform(0.0, 2.0 * np.pi, len(f))
    return np.sum(amp[:, None] * np.cos(2.0 * np.pi * f[:, None] * t[None, :] + phase[:, None]), axis=0)


def _unavailable(req: WaveSurrogateRequest, reason: str) -> WaveSurrogateResult:
    return WaveSurrogateResult(state="unavailable", seed=req.seed, reasons=[reason])


def generate(req: WaveSurrogateRequest) -> WaveSurrogateResult:
    spec: WaveSpectrumInput | None = req.spectrum
    if spec is None:
        return _unavailable(req, "No wave spectrum supplied; waves are unavailable, not zero. Baseline motion must not be presented as a wave-free prediction.")
    n = int(math.floor(req.duration_s / req.dt_s + 1e-9))
    t = np.arange(n) * req.dt_s
    notes, comps = [], {}
    for i, c in enumerate(spec.components):
        if c.peak_period_s < 2.0 * req.dt_s:
            return _unavailable(req, f"dt_s={req.dt_s:g} s cannot resolve peak period {c.peak_period_s:g} s (need dt <= Tp/2).")
        try:
            comps[c.label] = _component_series(c, t, req.duration_s, req.dt_s, req.seed, i)
        except ValueError as e:
            return _unavailable(req, str(e))
    total = np.zeros_like(t)
    for x in comps.values():
        total = total + x
    target = math.sqrt(sum(c.hs_ft**2 for c in spec.components))
    if spec.kind == "partitions" and spec.reported_total_hs_ft is not None and target > 0:
        if abs(spec.reported_total_hs_ft - target) > PARTITION_TOTAL_TOLERANCE * target:
            notes.append(f"Reported total Hs {spec.reported_total_hs_ft:g} ft differs from the partition energy sum {target:.3g} ft by more than "
                         f"{PARTITION_TOTAL_TOLERANCE:.0%}; partitions were used and the total was NOT added.")
        else:
            notes.append("Reported total Hs is consistent with the partitions; it was not added on top of them.")
    realized = 4.0 * float(np.std(total)) if len(total) else None
    zc = _mean_zero_crossing_period(total, req.dt_s)
    return WaveSurrogateResult(
        state="synthetic", seed=req.seed, source=spec.source, target_hs_ft=target, realized_hs_ft=realized, mean_zero_crossing_period_s=zc,
        series=WaveSurrogateSeries(t_s=t.tolist(), elevation_ft=total.tolist(), components={k: v.tolist() for k, v in comps.items()}),
        notes=notes + ["Direction is metadata only; no directional spreading, shoaling, sheltering or ship response is modeled."])


def _mean_zero_crossing_period(x: np.ndarray, dt: float) -> float | None:
    if len(x) < 3 or not np.any(x):
        return None
    up = int(np.sum((x[:-1] < 0) & (x[1:] >= 0)))
    return None if up == 0 else (len(x) - 1) * dt / up


def superpose(baseline: list[float], waves: WaveSurrogateResult) -> tuple[list[float], bool]:
    """Add a wave elevation series to a baseline of the same length. Returns (series, wave_applied).

    Unavailable waves leave the baseline untouched and report wave_applied=False (missing is not zero). Explicit zero-height
    waves add exactly 0.0 and return values equal to the baseline.
    """
    if waves.state != "synthetic" or waves.series is None:
        return list(baseline), False
    if len(waves.series.elevation_ft) != len(baseline):
        raise ValueError("baseline and wave series must have the same length")
    return [b + w for b, w in zip(baseline, waves.series.elevation_ft)], True
