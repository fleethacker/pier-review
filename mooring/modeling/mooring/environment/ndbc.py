"""NOAA/NDBC native wave-product parsing and bounded realtime acquisition."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from mooring.core.schemas import OffshoreWavePoint, WaveBulkParameters, WaveSpectrum, WaveSpectrumBin

from .errors import ProviderError
from .providers import HttpPolicy, ProviderHttpClient, bounded_httpx_transport

M_TO_FT = 3.28084
BASE_URL = "https://www.ndbc.noaa.gov/data/realtime2"
SPECTRAL_PRODUCTS = ("data_spec", "swdir", "swdir2", "swr1", "swr2")

STATIONS = {
    "44099": {"latitude_deg": 36.915, "longitude_deg": -75.722, "water_depth_m": 15.0},
    "44014": {"latitude_deg": 36.603, "longitude_deg": -74.837, "water_depth_m": 49.1},
}

_DIRECTION_DEG = {
    name: index * 22.5
    for index, name in enumerate(
        ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    )
}
_PAIR = re.compile(r"([-+]?\d+(?:\.\d+)?)\s+\(([-+]?\d+(?:\.\d+)?)\)")


def _time(tokens: list[str]) -> datetime:
    try:
        return datetime(*(int(value) for value in tokens[:5]), tzinfo=UTC)
    except (TypeError, ValueError):
        raise ProviderError("malformed", "NDBC row has an invalid UTC timestamp") from None


def _number(value: str) -> float | None:
    if value.upper() in {"MM", "N/A"}:
        return None
    try:
        parsed = float(value)
    except ValueError:
        raise ProviderError("malformed", f"NDBC numeric field is invalid: {value!r}") from None
    if not math.isfinite(parsed):
        raise ProviderError("malformed", f"NDBC numeric field is not finite: {value!r}")
    return None if parsed >= 999 else parsed


def _direction(value: str) -> float | None:
    if value.upper() in {"MM", "N/A"}:
        return None
    if value.upper() in _DIRECTION_DEG:
        return _DIRECTION_DEG[value.upper()]
    numeric = _number(value)
    if numeric is None:
        return None
    if not 0 <= numeric < 360:
        raise ProviderError("malformed", f"NDBC direction is outside [0, 360): {value!r}")
    return numeric


def parse_summary(text: str) -> list[OffshoreWavePoint]:
    """Parse native ``.spec`` rows without conflating total sea and partitions."""
    points = []
    seen = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 15:
            raise ProviderError("malformed", "NDBC detailed wave-summary row has too few fields")
        at = _time(fields)
        if at in seen:
            raise ProviderError("malformed", "NDBC detailed wave-summary product has duplicate timestamps")
        seen.add(at)
        wave_height, swell_height, swell_period = (_number(fields[index]) for index in (5, 6, 7))
        wind_height, wind_period = (_number(fields[index]) for index in (8, 9))
        swell_direction, wind_direction = _direction(fields[10]), _direction(fields[11])
        average_period, mean_direction = _number(fields[13]), _direction(fields[14])
        original: dict[str, float | str] = {
            "STEEPNESS": fields[12],
            "source_product": "spec",
        }
        for name, value in {
            "WVHT_m": wave_height,
            "SwH_m": swell_height,
            "SwP_s": swell_period,
            "WWH_m": wind_height,
            "WWP_s": wind_period,
            "APD_s": average_period,
            "MWD_degT": mean_direction,
        }.items():
            if value is not None:
                original[name] = value
        if fields[10].upper() not in {"MM", "N/A"}:
            original["SwD"] = fields[10]
        if fields[11].upper() not in {"MM", "N/A"}:
            original["WWD"] = fields[11]

        total = None
        if wave_height is not None:
            total = WaveBulkParameters(
                component="total_sea",
                significant_height_ft=wave_height * M_TO_FT,
                period_s=average_period,
                period_basis="average" if average_period is not None else "unknown",
                direction_from_true_deg=mean_direction,
                # NOAA detailed-wave-summary MWD is the direction at the dominant
                # period, not an all-frequency mean: ndbc.noaa.gov/faq/measdes.shtml#spec.
                direction_basis="dominant" if mean_direction is not None else "unknown",
            )
        partitions = []
        for component, height, period, direction in (
            ("swell", swell_height, swell_period, swell_direction),
            ("wind_sea", wind_height, wind_period, wind_direction),
        ):
            if height is not None:
                partitions.append(WaveBulkParameters(
                    component=component,
                    significant_height_ft=height * M_TO_FT,
                    period_s=period,
                    period_basis="provider_partition" if period is not None else "unknown",
                    direction_from_true_deg=direction,
                    direction_basis="provider_partition" if direction is not None else "unknown",
                ))
        if total is not None or partitions:
            points.append(OffshoreWavePoint(
                valid_at_utc=at,
                timestamp_basis="unknown",
                total_sea=total,
                partitions=partitions,
                original=original,
            ))
    if not points:
        raise ProviderError("no_data", "NDBC detailed wave-summary product has no usable rows")
    return points


@dataclass(frozen=True)
class SpectralRow:
    valid_at_utc: datetime
    product: str
    values: tuple[tuple[float, float | None], ...]
    separation_frequency_hz: float | None = None


def parse_spectral_product(text: str, product: str) -> list[SpectralRow]:
    """Parse one native density/alpha/r product; 999 fill values remain missing."""
    if product not in SPECTRAL_PRODUCTS:
        raise ValueError(f"unsupported NDBC spectral product {product!r}")
    rows = []
    seen = set()
    expected_frequencies: tuple[float, ...] | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split(maxsplit=6)
        if len(fields) < 7:
            raise ProviderError("malformed", f"NDBC {product} row has too few fields")
        at = _time(fields)
        if at in seen:
            raise ProviderError("malformed", f"NDBC {product} product has duplicate timestamps")
        seen.add(at)
        separation = _number(fields[5]) if product == "data_spec" else None
        if product == "data_spec" and separation == 9.999:
            separation = None
        pairs_text = fields[6] if product == "data_spec" else f"{fields[5]} {fields[6]}"
        matches = list(_PAIR.finditer(pairs_text))
        remainder = _PAIR.sub("", pairs_text).strip()
        if remainder:
            raise ProviderError("malformed", f"NDBC {product} row has unparsed frequency/value content")
        pairs = tuple((float(match.group(2)), _number(match.group(1))) for match in matches)
        if not pairs:
            raise ProviderError("malformed", f"NDBC {product} row has no frequency/value pairs")
        if any(b[0] <= a[0] for a, b in zip(pairs, pairs[1:])):
            raise ProviderError("malformed", f"NDBC {product} frequencies are not strictly increasing")
        frequencies = tuple(frequency for frequency, _ in pairs)
        if expected_frequencies is None:
            expected_frequencies = frequencies
        elif frequencies != expected_frequencies:
            raise ProviderError("malformed", f"NDBC {product} frequency bins change between rows")
        rows.append(SpectralRow(at, product, pairs, separation))
    if not rows:
        raise ProviderError("no_data", f"NDBC {product} product has no usable rows")
    return rows


def _coverage(values: list[float | None], *, expected: int) -> str:
    present = sum(value is not None for value in values)
    if not present:
        return "unavailable"
    return "complete" if present == expected else "partial"


def merge_spectral_products(products: Mapping[str, str]) -> dict[datetime, tuple[WaveSpectrum, dict[str, float | str]]]:
    """Join native products by timestamp/frequency without reconstructing a 2-D spectrum."""
    by_time: dict[datetime, dict[str, SpectralRow]] = {}
    for product, text in products.items():
        for row in parse_spectral_product(text, product):
            by_time.setdefault(row.valid_at_utc, {})[product] = row

    merged = {}
    fields = {
        "data_spec": "energy_density_m2_per_hz",
        "swdir": "alpha1_direction_from_true_deg",
        "swdir2": "alpha2_direction_from_true_deg",
        "swr1": "r1",
        "swr2": "r2",
    }
    coverage_fields = {
        "data_spec": "density_coverage",
        "swdir": "alpha1_coverage",
        "swdir2": "alpha2_coverage",
        "swr1": "r1_coverage",
        "swr2": "r2_coverage",
    }
    for at, rows in by_time.items():
        frequencies = sorted({frequency for row in rows.values() for frequency, _ in row.values})
        values_by_product = {
            product: dict(row.values) for product, row in rows.items()
        }
        bins = []
        for frequency in frequencies:
            values = {
                fields[product]: values_by_product.get(product, {}).get(frequency)
                for product in fields
            }
            bins.append(WaveSpectrumBin(frequency_hz=frequency, **values))
        states = {
            coverage_fields[product]: _coverage(
                [values_by_product.get(product, {}).get(frequency) for frequency in frequencies],
                expected=len(frequencies),
            )
            for product in fields
        }
        has_coefficients = any(states[name] != "unavailable" for name in (
            "alpha1_coverage", "alpha2_coverage", "r1_coverage", "r2_coverage"
        ))
        if states["density_coverage"] == "unavailable" and not has_coefficients:
            continue
        spectrum = WaveSpectrum(
            representation="ndbc_fourier_coefficients" if has_coefficients else "frequency_density",
            frequency_bin_count=len(frequencies),
            bins=bins,
            **states,
        )
        original: dict[str, float | str] = {"source_products": ",".join(sorted(rows))}
        density = rows.get("data_spec")
        if density is not None and density.separation_frequency_hz is not None:
            original["Sep_Freq"] = density.separation_frequency_hz
        merged[at] = spectrum, original
    return merged


def combine_points(summary: list[OffshoreWavePoint], spectra) -> list[OffshoreWavePoint]:
    by_time = {point.valid_at_utc.astimezone(UTC): point for point in summary}
    for at, (spectrum, original) in spectra.items():
        existing = by_time.get(at)
        if existing is None:
            by_time[at] = OffshoreWavePoint(
                valid_at_utc=at,
                timestamp_basis="unknown",
                spectrum=spectrum,
                original=original,
            )
        else:
            by_time[at] = existing.model_copy(update={
                "spectrum": spectrum,
                "original": {**(existing.original or {}), **original},
            })
    return [by_time[at] for at in sorted(by_time)]


@dataclass(frozen=True)
class FetchedProduct:
    text: str
    retrieved_at_utc: datetime
    source_url: str


class NDBCRealtime:
    """Small injectable reader for public NDBC realtime text products."""

    def __init__(self, client: ProviderHttpClient | None = None, *, max_product_bytes: int = 2_000_000):
        if type(max_product_bytes) is not int or max_product_bytes <= 0:
            raise ValueError("max_product_bytes must be a positive integer")
        self.client = client or ProviderHttpClient(
            provider_id="ndbc",
            policy=HttpPolicy(timeout_s=5, retries=0, min_interval_s=0.25, cache_ttl_s=300, max_stale_s=900),
            transport=partial(
                bounded_httpx_transport,
                max_response_bytes=max_product_bytes,
                max_elapsed_s=5.0,
            ),
        )
        self.max_product_bytes = max_product_bytes

    def fetch(
        self,
        station_id: str,
        product: str,
        *,
        deadline_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> FetchedProduct:
        if station_id not in STATIONS or product not in {"spec", *SPECTRAL_PRODUCTS}:
            raise ProviderError("invalid_request", "unsupported NDBC station or wave product")
        url = f"{BASE_URL}/{station_id}.{product}"
        budget = {} if deadline_monotonic is None else {
            "deadline_monotonic": deadline_monotonic,
            "monotonic": monotonic,
        }
        payload = self.client.get(url, **budget)
        if payload.status_code == 404:
            raise ProviderError("no_data", f"NDBC {station_id}.{product} is unavailable")
        if not 200 <= payload.status_code < 300:
            raise ProviderError("unavailable", f"NDBC {station_id}.{product} returned HTTP {payload.status_code}")
        if payload.stale:
            raise ProviderError("stale", f"NDBC {station_id}.{product} came from stale cache")
        if len(payload.content) > self.max_product_bytes:
            raise ProviderError(
                "unavailable",
                f"NDBC {station_id}.{product} exceeds the {self.max_product_bytes}-byte response limit",
            )
        try:
            text = payload.content.decode("utf-8")
        except UnicodeDecodeError:
            raise ProviderError("malformed", f"NDBC {station_id}.{product} is not UTF-8 text") from None
        retrieved = getattr(payload, "retrieved_at_utc", None)
        if retrieved is None:
            raise ProviderError("malformed", f"NDBC {station_id}.{product} has no recorded retrieval time")
        retrieved = retrieved.astimezone(UTC)
        return FetchedProduct(text=text, retrieved_at_utc=retrieved, source_url=url)


@dataclass(frozen=True)
class ObservationAcquisition:
    points: tuple[OffshoreWavePoint, ...]
    product_ids: tuple[str, ...]
    retrieved_at_utc: datetime
    limitations: tuple[str, ...]


class NDBCStationAdapter:
    def __init__(
        self,
        realtime: NDBCRealtime | None = None,
        *,
        total_timeout_s: float = 20.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not math.isfinite(total_timeout_s) or total_timeout_s <= 0:
            raise ValueError("total_timeout_s must be finite and positive")
        self.realtime = realtime or NDBCRealtime()
        self.total_timeout_s = total_timeout_s
        self.monotonic = monotonic

    def acquire(
        self,
        station_id: str,
        *,
        as_of_utc: datetime,
        lookback_hours: int,
        include_spectrum: bool,
        max_elapsed_s: float | None = None,
    ) -> ObservationAcquisition:
        started = self.monotonic()
        budget = self.total_timeout_s if max_elapsed_s is None else min(self.total_timeout_s, max_elapsed_s)
        if not math.isfinite(budget) or budget <= 0:
            raise ProviderError("unavailable", "NDBC station acquisition has no remaining time budget")
        deadline = started + budget

        def deadline_exceeded() -> bool:
            return self.monotonic() >= deadline

        fetch_budget = {"deadline_monotonic": deadline, "monotonic": self.monotonic}
        summary = self.realtime.fetch(station_id, "spec", **fetch_budget)
        if deadline_exceeded():
            raise ProviderError("unavailable", "NDBC station acquisition exceeded its total deadline")
        cutoff = as_of_utc.astimezone(UTC)
        if summary.retrieved_at_utc.astimezone(UTC) > cutoff:
            raise ProviderError("unavailable", "NDBC summary was retrieved after the request as_of_utc")
        summary_points = parse_summary(summary.text)
        if any(point.valid_at_utc.astimezone(UTC) > summary.retrieved_at_utc.astimezone(UTC) for point in summary_points):
            raise ProviderError("malformed", "NDBC summary contains a row later than its recorded retrieval")
        product_text: dict[str, str] = {}
        fetched = [summary]
        limitations = [
            "Provider sample bounds and timestamp position are not documented by the selected realtime text product.",
            "NDBC data are an offshore boundary condition; no berth transfer is established.",
        ]
        if include_spectrum:
            for product in SPECTRAL_PRODUCTS:
                if deadline_exceeded():
                    limitations.append("Remaining NDBC spectra omitted: station acquisition total deadline reached.")
                    break
                try:
                    item = self.realtime.fetch(station_id, product, **fetch_budget)
                    if deadline_exceeded():
                        raise ProviderError("unavailable", "station acquisition total deadline reached")
                    if item.retrieved_at_utc.astimezone(UTC) > cutoff:
                        raise ProviderError("unavailable", "retrieved after as_of_utc")
                    parsed = parse_spectral_product(item.text, product)
                    if any(row.valid_at_utc.astimezone(UTC) > item.retrieved_at_utc.astimezone(UTC) for row in parsed):
                        raise ProviderError("malformed", "product contains a row later than its recorded retrieval")
                    product_text[product] = item.text
                    fetched.append(item)
                except ProviderError as exc:
                    limitations.append(f"NDBC {product} omitted: {exc.kind}: {exc}")
        spectra = {}
        if product_text:
            try:
                spectra = merge_spectral_products(product_text)
            except (ProviderError, ValueError) as exc:
                limitations.append(f"NDBC spectra omitted: malformed native product set: {exc}")
                fetched = [summary]
        points = combine_points(summary_points, spectra)
        start = cutoff - timedelta(hours=lookback_hours)
        points = [point for point in points if start <= point.valid_at_utc.astimezone(UTC) <= cutoff]
        if not points:
            raise ProviderError("no_data", "NDBC has no usable wave rows in the requested observation lookback")
        return ObservationAcquisition(
            points=tuple(points),
            product_ids=tuple(item.source_url for item in fetched),
            retrieved_at_utc=max(item.retrieved_at_utc.astimezone(UTC) for item in fetched),
            limitations=tuple(limitations),
        )
