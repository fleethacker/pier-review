"""Stochastic environment tools (S10): fitting, qualification and seeded sampling.

What is random: gust factor (gust / sustained), wind direction scatter, current-speed residual, and their temporal
correlation (AR(1) in log-wind and current deviations). Not modeled: forecast error (cannot be fitted from observations
alone), tide error, hurricane/storm-force winds, direction/speed/current dependence beyond what is stated.

Nothing here is a validated risk model. `SYNTHETIC_DEMO` carries the constants the old mock used and is labeled
unqualified. A fitted model becomes `qualified` only by passing `qualify()`: the minimum-data policy and held-out
calibration. Fitting and validation data must be split by time/event (`split_by_event`) to avoid leakage; this module
fits from arrays you give it and never downloads data. Probabilities from an unqualified model are scenario outputs.
"""

import math
import random
import statistics
from collections.abc import Sequence
from datetime import datetime

from mooring.core.schemas import EnvironmentSnapshot, HeldOutValidation, UncertaintyModel, UncertaintySector

MIN_EVENTS = 30            # independent events (storm episodes / days) required
MIN_DAYS = 365.0           # span of fitting data
COVERAGE_BAND = (0.80, 0.97)   # acceptable observed coverage for a nominal 90% interval
MAX_WIND_KT, MAX_CURRENT_KT = 150.0, 8.0   # physical bounds on sampled values


# ---------- circular statistics ----------

def circular_mean_deg(angles: Sequence[float]) -> float:
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return round(math.degrees(math.atan2(s, c)), 9) % 360


def circular_std_deg(angles: Sequence[float]) -> float:
    """sqrt(-2 ln R) in degrees; R is the mean resultant length."""
    n = len(angles)
    r = math.hypot(sum(math.sin(math.radians(a)) for a in angles), sum(math.cos(math.radians(a)) for a in angles)) / n
    return math.degrees(math.sqrt(-2.0 * math.log(max(r, 1e-12))))


def angle_diff_deg(a: float, b: float) -> float:
    """Signed smallest difference a - b in (-180, 180]; 359 and 1 are 2 degrees apart."""
    return (a - b + 180.0) % 360.0 - 180.0


# ---------- fitting ----------

def fit_lognormal(xs: Sequence[float]) -> tuple[float, float]:
    logs = [math.log(x) for x in xs if x > 0]
    if len(logs) < 2:
        raise ValueError("need at least two positive values to fit a lognormal")
    return statistics.fmean(logs), statistics.stdev(logs)


def fit_gust_sectors(records: Sequence[tuple[float, float]], width_deg: int = 45) -> list[UncertaintySector]:
    """Fit gust factor by true-direction sector, omitting sectors with fewer than two samples."""
    if width_deg <= 0 or 360 % width_deg:
        raise ValueError("sector width must divide 360")
    result = []
    for start in range(0, 360, width_deg):
        values = [(direction % 360, factor) for direction, factor in records if start <= direction % 360 < start + width_deg and factor > 0]
        if len(values) < 2:
            continue
        mu, sigma = fit_lognormal([factor for _, factor in values])
        result.append(UncertaintySector(from_deg=start, to_deg=start + width_deg, gust_factor_mu=mu, gust_factor_sigma=sigma,
                                        direction_sigma_deg=circular_std_deg([direction for direction, _ in values]), n_fit=len(values)))
    return result


def fit_ar1(series: Sequence[float], dt_min: float) -> tuple[float, float, float]:
    """(phi, innovation sigma, correlation time in minutes) by lag-1 autocorrelation of a deviation series."""
    n = len(series)
    if n < 3:
        raise ValueError("need at least three points to fit AR(1)")
    m = statistics.fmean(series)
    d = [x - m for x in series]
    var = sum(x * x for x in d) / n
    if var == 0:
        raise ValueError("series has no variance")
    phi = max(min(sum(d[i] * d[i + 1] for i in range(n - 1)) / (n * var), 0.999999), 1e-6)
    return phi, math.sqrt(var * (1 - phi * phi)), -dt_min / math.log(phi)


def split_by_event(items: Sequence[tuple[datetime, str, object]], heldout_fraction: float = 0.3):
    """Time-blocked split by event id: the latest events are held out whole, so no event straddles fit and validation.

    `items` are (time, event_id, value). Returns (fit_values, heldout_values)."""
    events = sorted({e for _, e, _ in items}, key=lambda e: min(t for t, ev, _ in items if ev == e))
    cut = max(1, int(round(len(events) * (1 - heldout_fraction))))
    fit_events = set(events[:cut])
    return [v for _, e, v in items if e in fit_events], [v for _, e, v in items if e not in fit_events]


def coverage(model: UncertaintyModel, heldout_gust_factors: Sequence[float], nominal: float = 0.90) -> HeldOutValidation:
    """Share of held-out gust factors inside the model's central `nominal` interval."""
    nd = statistics.NormalDist(model.gust_factor_mu, max(model.gust_factor_sigma, 1e-12))
    lo, hi = nd.inv_cdf((1 - nominal) / 2), nd.inv_cdf(1 - (1 - nominal) / 2)
    inside = sum(1 for g in heldout_gust_factors if g > 0 and lo <= math.log(g) <= hi)
    return HeldOutValidation(n_heldout=len(heldout_gust_factors), nominal_coverage=nominal,
                             observed_coverage=inside / len(heldout_gust_factors) if heldout_gust_factors else None)


def qualify(model: UncertaintyModel) -> UncertaintyModel:
    """Apply the minimum-data policy and held-out calibration; returns a copy with qualification and reasons set."""
    reasons = []
    if model.kind == "synthetic":
        reasons.append("Synthetic distribution: validates algorithms only.")
    if model.n_events < MIN_EVENTS:
        reasons.append(f"Only {model.n_events} independent events; the policy needs at least {MIN_EVENTS}.")
    if model.n_days < MIN_DAYS:
        reasons.append(f"Only {model.n_days:g} days of data; the policy needs at least {MIN_DAYS:g}.")
    if model.validation is None or model.validation.observed_coverage is None:
        reasons.append("No held-out calibration.")
    elif not COVERAGE_BAND[0] <= model.validation.observed_coverage <= COVERAGE_BAND[1]:
        reasons.append(f"Held-out coverage {model.validation.observed_coverage:.2f} is outside {COVERAGE_BAND} for a nominal "
                       f"{model.validation.nominal_coverage:.2f} interval.")
    reasons.append("Hurricane and storm-force winds are outside the data and the model; forecast error is not modeled.")
    ok = not [r for r in reasons if not r.startswith("Hurricane")]
    return model.model_copy(update={"qualification": "qualified" if ok else "unqualified", "qualification_reasons": reasons})


SYNTHETIC_DEMO = UncertaintyModel(
    model_id="synthetic-demo", revision="1", kind="synthetic", gust_factor_mu=0.27, gust_factor_sigma=0.08,
    direction_sigma_deg=15.0, current_sigma_kt=0.15, correlation_time_min=30.0, n_events=0, n_days=0.0,
    applicability=["Algorithm validation and deterministic what-if scenarios."],
    limitations=["Not fitted to any station.", "No forecast error, tide error or storm winds."], qualification="unqualified",
    qualification_reasons=["Synthetic distribution: validates algorithms only.", "No fitting data.", "No held-out calibration."])


# ---------- sampling ----------

class Sampler:
    """Seeded, reproducible sampling around a base environment. Same seed and model give the same draws on any machine."""

    def __init__(self, model: UncertaintyModel, seed: int | None):
        self.model, self.rng = model, random.Random(seed)

    def _gust_factor(self, z: float) -> float:
        return math.exp(self.model.gust_factor_mu + self.model.gust_factor_sigma * z)

    def _apply(self, base: EnvironmentSnapshot, z_gust: float, dir_dev_deg: float, cur_dev_kt: float) -> EnvironmentSnapshot:
        gf = max(self._gust_factor(z_gust), 1.0)  # a gust is never below the sustained wind
        sustained = min(base.wind_speed_kt, MAX_WIND_KT)
        return base.model_copy(update={
            "wind_gust_kt": min(sustained * gf, MAX_WIND_KT),
            "wind_from_true_deg": (base.wind_from_true_deg + dir_dev_deg) % 360.0,
            "current_speed_kt": min(max(0.0, base.current_speed_kt + cur_dev_kt), MAX_CURRENT_KT)})

    def instant(self, base: EnvironmentSnapshot) -> EnvironmentSnapshot:
        m = self.model
        return self._apply(base, self.rng.gauss(0, 1), self.rng.gauss(0, m.direction_sigma_deg), self.rng.gauss(0, m.current_sigma_kt))

    def trajectory(self, base: EnvironmentSnapshot, n_steps: int, step_min: float) -> list[EnvironmentSnapshot]:
        """Time-correlated path: each deviation is AR(1) with the model's correlation time, stationary at its marginal."""
        m = self.model
        phi = math.exp(-step_min / m.correlation_time_min)
        inn = math.sqrt(1 - phi * phi)
        zg, zd, zc = self.rng.gauss(0, 1), self.rng.gauss(0, 1), self.rng.gauss(0, 1)
        out = []
        for _ in range(n_steps):
            out.append(self._apply(base, zg, zd * m.direction_sigma_deg, zc * m.current_sigma_kt))
            zg = phi * zg + inn * self.rng.gauss(0, 1)
            zd = phi * zd + inn * self.rng.gauss(0, 1)
            zc = phi * zc + inn * self.rng.gauss(0, 1)
        return out


# ---------- committed model artifacts ----------

MODELS_DIR = __import__("pathlib").Path(__file__).parent / "models"


def available_models() -> list[str]:
    return [SYNTHETIC_DEMO.model_id] + sorted(p.stem for p in MODELS_DIR.glob("*.json"))


def load_model(model_id: str) -> UncertaintyModel:
    """The synthetic demo or a committed fitted artifact (parameters and provenance only; the artifact's qualification is re-derived)."""
    if model_id == SYNTHETIC_DEMO.model_id:
        return SYNTHETIC_DEMO
    path = MODELS_DIR / f"{model_id}.json"
    if "/" in model_id or ".." in model_id or not path.is_file():
        raise KeyError(model_id)
    return qualify(UncertaintyModel.model_validate_json(path.read_text()))
