"""NOAA CO-OPS provider adapter (S04b): observations and predictions, validated against the published API.

Verified against the CO-OPS Data API documentation and live responses on 4 Nov 2026 (see the recorded fixtures in
`fixtures/coops/`): products `wind`, `water_level`, `currents`, `predictions`, `currents_predictions`; mandatory `datum`
for water-level products; mandatory `bin` for currents; `time_zone=gmt`, `units=english` (feet, knots), `format=json`;
6-minute data limited to one month per request, predictions other than hilo one year, current predictions other than
max_slack one month; error bodies are `{"error": {"message": ...}}`. Not verified from the docs available: the meaning
of the current `d` field (treated as the direction the current flows TOWARD, the usual NOAA convention); this is listed
as an assumption in every result's metadata source string and should be confirmed against CO-OPS before live use.

Findings that shaped the design:
* The seed stations are right: wind 8638614 (Willoughby Degaussing), water level 8638610 (Sewells Point), currents cb0402
  (Naval Station Norfolk). Wind is NOT offered at 8638610. Current observation bins and prediction bins differ by
  station: cb0402 predictions list bins 4, 8 and 11 only; observations exist for bins 1-12 at different depths. Bin 4
  (about 20.6 ft below the surface, the station's real-time bin) is the one used for both; the bin and its depth travel in
  the metadata.
* The current series is timestamped about 2 minutes off the wind and water-level series (e.g. 00:02 vs 00:00), so series
  are joined by nearest timestamp within a tolerance, never by exact match and never by interpolation across a gap.
* The 6-minute reporting interval does not establish the wind averaging duration; it is left unknown in metadata.

No synthetic data is ever substituted on failure: errors surface as `ProviderError` with a kind.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .errors import ProviderError
from .providers import HttpPayload, HttpPolicy, ProviderHttpClient, provider_config

BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
APPLICATION = "mooring-assistant"
DAYS = {"wind": 31, "water_level": 31, "currents": 31, "predictions": 365, "currents_predictions": 31}
ASSUMED_CURRENT_DIRECTION = "current direction d assumed to be the direction the current flows toward (to be confirmed with CO-OPS)"
ALIGN_TOLERANCE_S = 180.0


# ---------- request building ----------

def request_params(product: str, station: str, begin: datetime, end: datetime, *, datum: str | None = None, bin: int | None = None,
                   interval: str | None = None) -> dict[str, str]:
    if product not in DAYS:
        raise ProviderError("invalid_request", f"unsupported product {product!r}")
    for t in (begin, end):
        if t.tzinfo is None:
            raise ProviderError("invalid_request", "begin and end need a timezone (they are sent as GMT)")
    b, e = begin.astimezone(UTC), end.astimezone(UTC)
    if e <= b:
        raise ProviderError("invalid_request", "end must be after begin")
    if (e - b) > timedelta(days=DAYS[product]):
        raise ProviderError("invalid_request", f"{product} requests are limited to {DAYS[product]} days; split the window")
    p = {"product": product, "station": station, "begin_date": b.strftime("%Y%m%d %H:%M"), "end_date": e.strftime("%Y%m%d %H:%M"),
         "time_zone": "gmt", "units": "english", "format": "json", "application": APPLICATION}
    if product in ("water_level", "predictions"):
        if not datum:
            raise ProviderError("invalid_request", f"{product} requires a datum")
        if datum != "MLLW":
            raise ProviderError("invalid_request", "only MLLW is accepted: water_level_mllw_ft is relative to MLLW (convert explicitly if needed)")
        p["datum"] = datum
    if product in ("currents", "currents_predictions"):
        if bin is None:
            raise ProviderError("invalid_request", f"{product} requires a bin; observation and prediction bins differ by station")
        p["bin"] = str(bin)
    if product == "currents_predictions":
        p["vel_type"] = "speed_dir"
        p["interval"] = interval or "6"
    if product == "predictions":
        p["interval"] = interval or "6"
    return p


# ---------- parsing (pure) ----------

def _check_error(doc: dict) -> None:
    if not isinstance(doc, dict):
        raise ProviderError("malformed", "response JSON is not an object")
    err = doc.get("error")
    if err:
        msg = str(err.get("message", err) if isinstance(err, dict) else err).strip()
        low = msg.lower()
        kind = "no_data" if "no data" in low else "bad_request"
        raise ProviderError(kind, msg)


def _t(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        raise ProviderError("malformed", f"unparseable timestamp {s!r}") from None


def _num(v) -> float | None:
    if v in (None, "", " "):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ProviderError("malformed", f"non-numeric value {v!r}") from None
    if x != x or abs(x) == float("inf"):
        raise ProviderError("malformed", "non-finite value")
    return x


def _flags(f: str | None) -> list[int]:
    try:
        return [int(x) for x in str(f or "").split(",") if x != ""]
    except ValueError:
        raise ProviderError("malformed", f"bad flags {f!r}") from None


def _data(doc: dict, key: str = "data") -> list[dict]:
    _check_error(doc)
    rows = doc.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProviderError("malformed", f"response '{key}' must be a list of objects")
    return rows


def _require_current_bin(rows: list[dict], requested_bin: int | str, *, field: str) -> None:
    if any(row.get(field) is not None and str(row[field]) != str(requested_bin) for row in rows):
        raise ProviderError("no_data", f"current response bin differs from requested bin {requested_bin}; no bin substitution is permitted")


def parse_wind(doc: dict) -> list[dict]:
    """t, speed (kt), direction FROM (deg true), gust (kt), quality. Wind flags (X max exceeded, R rate exceeded) mark suspect."""
    out = []
    for r in _data(doc):
        flags = _flags(r.get("f"))
        out.append({"t": _t(r.get("t")), "wind_speed_kt": _num(r.get("s")), "wind_from_true_deg": _num(r.get("d")), "wind_gust_kt": _num(r.get("g")),
                    "quality": "suspect" if any(flags) else "good", "original": dict(r)})
    return out


def parse_water_level(doc: dict) -> list[dict]:
    """Water level in feet above the requested datum (MLLW). Any raised quality flag marks suspect; q='p' is preliminary data."""
    out = []
    for r in _data(doc):
        flags = _flags(r.get("f"))
        out.append({"t": _t(r.get("t")), "water_level_ft": _num(r.get("v")), "quality": "suspect" if any(flags) else "good",
                    "preliminary": r.get("q") == "p", "original": dict(r)})
    return out


def parse_currents(doc: dict, *, expected_bin: int | str | None = None) -> list[dict]:
    out = []
    rows = _data(doc)
    if expected_bin is not None:
        _require_current_bin(rows, expected_bin, field="b")
    for r in rows:
        out.append({"t": _t(r.get("t")), "current_speed_kt": _num(r.get("s")), "current_set_true_deg": _num(r.get("d")), "bin": r.get("b"),
                    "quality": "good", "original": dict(r)})
    return out


def parse_predictions(doc: dict) -> list[dict]:
    _check_error(doc)
    rows = doc.get("predictions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProviderError("malformed", "response predictions must be a list of objects")
    return [{"t": _t(r.get("t")), "water_level_ft": _num(r.get("v"))} for r in rows]


def parse_current_predictions(doc: dict) -> list[dict]:
    _check_error(doc)
    predictions = doc.get("current_predictions")
    rows = predictions.get("cp") if isinstance(predictions, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProviderError("malformed", "response current_predictions.cp must be a list of objects")
    return [{"t": _t(r.get("Time")), "current_speed_kt": _num(r.get("Speed")), "current_set_true_deg": _num(r.get("Direction")),
             "bin": r.get("Bin"), "depth_ft": _num(r.get("Depth"))} for r in rows]


# ---------- joining ----------

def _nearest(series: list[dict], t: datetime, tol_s: float) -> dict | None:
    best = min(series, key=lambda r: abs((r["t"] - t).total_seconds()), default=None)
    return best if best is not None and abs((best["t"] - t).total_seconds()) <= tol_s else None


def assemble(wind: list[dict], level: list[dict], current: list[dict], *, wind_station: str, level_station: str, current_station: str, bin: int,
             bin_depth_ft: float | None = None, tol_s: float = ALIGN_TOLERANCE_S) -> tuple[list[dict], list[str]]:
    """Raw records for `ReplaySource`, joined on the wind timestamps. Returns (records, notes about dropped timestamps)."""
    _require_current_bin(current, bin, field="bin")
    out, notes = [], []
    for w in wind:
        lv, cu = _nearest(level, w["t"], tol_s), _nearest(current, w["t"], tol_s)
        missing = [name for name, v in (("water level", lv), ("current", cu)) if v is None]
        fields = {"wind_speed_kt": w["wind_speed_kt"], "wind_gust_kt": w["wind_gust_kt"], "wind_from_true_deg": w["wind_from_true_deg"]}
        if lv is not None:
            fields["water_level_ft"] = lv["water_level_ft"]
        if cu is not None:
            fields["current_speed_kt"], fields["current_set_true_deg"] = cu["current_speed_kt"], cu["current_set_true_deg"]
        absent = [k for k, v in fields.items() if v is None] + [f"{m} (no sample within {tol_s:g} s)" for m in missing]
        if absent or len(fields) < 6:
            notes.append(f"{w['t'].isoformat()}: dropped, missing {', '.join(absent) or 'fields'}")
            continue
        qualities = [w["quality"], lv["quality"], cu["quality"]]
        quality = "poor" if "poor" in qualities else "suspect" if "suspect" in qualities else "good"
        out.append({"t": w["t"].isoformat(), **fields, "quality": quality, "current_bin": str(bin), "current_depth_ft": bin_depth_ft,
                    "source": f"NOAA CO-OPS wind {wind_station}, water level {level_station}, currents {current_station} bin {bin}; {ASSUMED_CURRENT_DIRECTION}",
                    "original": {**{f"wind_{k}": str(v) for k, v in w["original"].items()},
                                 **{f"level_{k}": str(v) for k, v in lv["original"].items()},
                                 **{f"current_{k}": str(v) for k, v in cu["original"].items()}}})
    return out, notes


# ---------- transport, retries, rate limit, cache ----------

Transport = Callable[[str, dict, float], tuple[int, str]]


def urllib_transport(url: str, params: dict, timeout_s: float) -> tuple[int, str]:
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=timeout_s) as r:   # noqa: S310 (fixed https host)
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@dataclass
class Fetched:
    doc: dict
    stale: bool
    age_s: float
    retrieved_at_utc: datetime | None = None


class Fetcher:
    """Timeouts, bounded retries, a minimum interval between calls, a TTL cache and an explicit stale-cache policy.

    The clock and sleep are injected so behavior is deterministic in tests. After retries are exhausted a cached answer no
    older than `max_stale_s` may be returned, flagged `stale=True`; otherwise `ProviderError('unavailable')`. API-level
    errors (error JSON) are never retried and never served from stale cache."""

    def __init__(self, transport: Transport = urllib_transport, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 sleep: Callable[[float], None] = time.sleep, timeout_s: float = 10.0, retries: int = 2, backoff_s: float = 1.0,
                 min_interval_s: float = 0.5, cache_ttl_s: float = 300.0, max_stale_s: float = 3600.0,
                 breaker_failures: int = 3, breaker_reset_s: float = 30.0, base_url: str | None = None):
        class InjectedClock:
            def now(self):
                return clock()

            def sleep(self, seconds):
                sleep(seconds)

        config = provider_config("coops", default_base_url=BASE_URL)
        self.base_url = base_url or config.base_url or BASE_URL
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self.timeout_s, self.retries, self.backoff_s = timeout_s, retries, backoff_s
        self.min_interval_s, self.cache_ttl_s, self.max_stale_s = min_interval_s, cache_ttl_s, max_stale_s
        def adapted(url, params, timeout, headers):
            status, text = transport(url, dict(params), timeout)
            return HttpPayload(status, text.encode("utf-8"), {})
        self.client = ProviderHttpClient(
            "NOAA CO-OPS",
            HttpPolicy(timeout_s, retries, backoff_s, min_interval_s, cache_ttl_s, max_stale_s,
                       breaker_failures, breaker_reset_s),
            InjectedClock(),
            adapted,
        )

    @property
    def cache(self):
        return self.client._cache

    @property
    def calls(self):
        return self.client.calls

    @property
    def breaker(self):
        return self.client.breaker

    def get(self, params: dict) -> Fetched:
        payload = self.client.get(self.base_url, {str(k): str(v) for k, v in params.items()})
        try:
            doc = payload.json()
        except ProviderError:
            self.client.invalidate(self.base_url, {str(k): str(v) for k, v in params.items()})
            raise
        if not isinstance(doc, dict):
            self.client.invalidate(self.base_url, {str(k): str(v) for k, v in params.items()})
            raise ProviderError("malformed", "response JSON is not an object")
        if "error" in doc:
            self.client.invalidate(self.base_url, {str(k): str(v) for k, v in params.items()})
        elif params.get("product") == "currents" and params.get("bin") is not None:
            try:
                _require_current_bin(_data(doc), params["bin"], field="b")
            except ProviderError:
                self.client.invalidate(self.base_url, {str(k): str(v) for k, v in params.items()})
                raise
        return Fetched(doc, payload.stale, payload.age_s, payload.retrieved_at_utc)


class Coops:
    """High-level reads for one set of stations. Uses a Fetcher; returns parsed records or raises ProviderError."""

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    def window(self, wind_station: str, level_station: str, current_station: str, begin: datetime, end: datetime, *, bin: int = 4,
               bin_depth_ft: float | None = None):
        """(raw records, notes, stale?) for ReplaySource. Components are fetched separately so each failure is attributable."""
        w = self.f.get(request_params("wind", wind_station, begin, end))
        lv = self.f.get(request_params("water_level", level_station, begin, end, datum="MLLW"))
        cu = self.f.get(request_params("currents", current_station, begin, end, bin=bin))
        recs, notes = assemble(parse_wind(w.doc), parse_water_level(lv.doc), parse_currents(cu.doc), wind_station=wind_station,
                               level_station=level_station, current_station=current_station, bin=bin, bin_depth_ft=bin_depth_ft)
        return recs, notes, any(x.stale for x in (w, lv, cu))

    def tide_predictions(self, station: str, begin: datetime, end: datetime):
        return parse_predictions(self.f.get(request_params("predictions", station, begin, end, datum="MLLW")).doc)

    def current_predictions(self, station: str, begin: datetime, end: datetime, bin: int = 4):
        return parse_current_predictions(self.f.get(request_params("currents_predictions", station, begin, end, bin=bin)).doc)
