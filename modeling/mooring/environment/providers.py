"""Shared provider plumbing for environmental data adapters (DC0).

The transport is intentionally independent of NOAA response shapes.  Later
adapters own parsing and normalization; this module owns network policy and
never manufactures environmental values when a provider cannot answer.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

import httpx

from mooring.core.schemas import EnvironmentSnapshot

from .errors import ProviderError

T = TypeVar("T")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class Available:
    """A provider value plus explicit cache provenance."""

    value: EnvironmentSnapshot
    stale: bool = False
    age_s: float = 0.0


@dataclass(frozen=True)
class Unavailable:
    """An explicit absence. Providers must return this, never fake a value."""

    reason_code: str
    detail: str


ProviderResult = Available | Unavailable


@runtime_checkable
class EnvironmentProvider(Protocol):
    """Stable minimum interface implemented by live and recorded providers."""

    provider_id: str

    def snapshot(self, at: datetime) -> ProviderResult: ...


@dataclass
class FixtureProvider:
    """Replay a checked-in JSON fixture through the provider interface."""

    path: Path
    basis: Literal["observation", "prediction", "scenario"]
    source_kind: Literal["replay", "forecast", "mock"]
    provider_id: str = "recorded-fixture"

    def __post_init__(self) -> None:
        from .replay import ReplaySource

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._source = ReplaySource(
            raw,
            station=self.provider_id,
            basis=self.basis,
            source_kind=self.source_kind,
        )

    def snapshot(self, at: datetime) -> ProviderResult:
        from .replay import Unavailable as ReplayUnavailable

        got = self._source.at(at, now=at)
        if isinstance(got, ReplayUnavailable):
            return Unavailable("NO_DATA", got.reason)
        return Available(got)


@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool = False
    base_url: str = ""


def provider_config(provider_id: str, *, default_base_url: str = "") -> ProviderConfig:
    """Read provider enable/base URL settings without accepting a secret."""

    import os

    key = provider_id.upper().replace("-", "_")
    raw_enabled = os.getenv(f"MOORING_PROVIDER_{key}_ENABLED", "false").strip().lower()
    if raw_enabled not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"MOORING_PROVIDER_{key}_ENABLED must be true or false")
    return ProviderConfig(
        enabled=raw_enabled in {"true", "1", "yes"},
        base_url=os.getenv(f"MOORING_PROVIDER_{key}_BASE_URL", default_base_url).rstrip("/"),
    )


@dataclass(frozen=True)
class HttpPolicy:
    timeout_s: float = 10.0
    retries: int = 2
    backoff_s: float = 1.0
    min_interval_s: float = 0.5
    cache_ttl_s: float = 300.0
    max_stale_s: float = 3600.0
    breaker_failures: int = 3
    breaker_reset_s: float = 30.0

    def __post_init__(self) -> None:
        nonnegative = (
            self.timeout_s,
            self.retries,
            self.backoff_s,
            self.min_interval_s,
            self.cache_ttl_s,
            self.max_stale_s,
            self.breaker_reset_s,
        )
        if (any(not math.isfinite(x) or x < 0 for x in nonnegative) or self.timeout_s <= 0 or
                type(self.retries) is not int or type(self.breaker_failures) is not int or self.breaker_failures < 1):
            raise ValueError("provider policy values must be finite/non-negative; timeout and integer breaker threshold positive; retries an integer")


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int
    reset_after_s: float
    clock: Clock
    state: BreakerState = BreakerState.CLOSED
    failures: int = 0
    opened_at: datetime | None = None

    def allow(self) -> None:
        if self.state != BreakerState.OPEN:
            return
        assert self.opened_at is not None
        if (self.clock.now() - self.opened_at).total_seconds() >= self.reset_after_s:
            self.state = BreakerState.HALF_OPEN
            return
        raise ProviderError("unavailable", "provider circuit breaker is open")

    def succeeded(self) -> None:
        self.state = BreakerState.CLOSED
        self.failures = 0
        self.opened_at = None

    def failed(self) -> None:
        self.failures += 1
        if self.state == BreakerState.HALF_OPEN or self.failures >= self.failure_threshold:
            self.state = BreakerState.OPEN
            self.opened_at = self.clock.now()


@dataclass(frozen=True)
class HttpPayload:
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    from_cache: bool = False
    stale: bool = False
    age_s: float = 0.0

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError("malformed", "provider response is not valid JSON") from None


Transport = Callable[[str, Mapping[str, str], float, Mapping[str, str]], HttpPayload]


def httpx_transport(url: str, params: Mapping[str, str], timeout_s: float, headers: Mapping[str, str]) -> HttpPayload:
    response = httpx.get(url, params=params, timeout=timeout_s, headers=headers, follow_redirects=False)
    return HttpPayload(response.status_code, response.content, dict(response.headers))


@dataclass
class ProviderHttpClient:
    """Deterministic provider HTTP policy with explicit stale-cache behavior."""

    provider_id: str
    policy: HttpPolicy = field(default_factory=HttpPolicy)
    clock: Clock = field(default_factory=SystemClock)
    transport: Transport = httpx_transport
    user_agent: str = "mooring-environment-client/0.1"

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self.breaker = CircuitBreaker(
            self.policy.breaker_failures,
            self.policy.breaker_reset_s,
            self.clock,
        )
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[datetime, HttpPayload]] = {}
        self._last_call: datetime | None = None
        self.calls = 0

    @staticmethod
    def _key(url: str, params: Mapping[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return url, tuple(sorted((str(k), str(v)) for k, v in params.items()))

    def _cached(self, payload: HttpPayload, *, age_s: float, stale: bool) -> HttpPayload:
        return HttpPayload(payload.status_code, payload.content, payload.headers, True, stale, age_s)

    def get(self, url: str, params: Mapping[str, str] | None = None) -> HttpPayload:
        # A shared provider client coalesces cache misses and serializes its rate/breaker state.
        with self._lock:
            return self._get(url, params)

    def _get(self, url: str, params: Mapping[str, str] | None = None) -> HttpPayload:
        params = params or {}
        key = self._key(url, params)
        now = self.clock.now()
        hit = self._cache.get(key)
        if hit:
            age_s = (now - hit[0]).total_seconds()
            if 0 <= age_s <= self.policy.cache_ttl_s:
                return self._cached(hit[1], age_s=age_s, stale=False)

        try:
            self.breaker.allow()
        except ProviderError:
            if hit:
                age_s = (self.clock.now() - hit[0]).total_seconds()
                if 0 <= age_s <= self.policy.max_stale_s:
                    return self._cached(hit[1], age_s=age_s, stale=True)
            raise
        last_error = "no attempt"
        for attempt in range(self.policy.retries + 1):
            if self._last_call is not None:
                wait = self.policy.min_interval_s - (self.clock.now() - self._last_call).total_seconds()
                if wait > 0:
                    self.clock.sleep(wait)
            self._last_call = self.clock.now()
            self.calls += 1
            try:
                payload = self.transport(
                    url,
                    params,
                    self.policy.timeout_s,
                    {"User-Agent": self.user_agent, "Accept": "application/json"},
                )
            except (httpx.HTTPError, OSError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if payload.status_code == 429 or payload.status_code >= 500:
                    last_error = f"HTTP {payload.status_code}"
                else:
                    self.breaker.succeeded()
                    if 200 <= payload.status_code < 300:
                        self._cache[key] = (self.clock.now(), payload)
                    return payload
            if attempt < self.policy.retries:
                self.clock.sleep(self.policy.backoff_s * (2**attempt))

        self.breaker.failed()
        if hit:
            # Retries, transport latency and backoff all age the cached value.
            age_s = (self.clock.now() - hit[0]).total_seconds()
            if 0 <= age_s <= self.policy.max_stale_s:
                return self._cached(hit[1], age_s=age_s, stale=True)
        raise ProviderError(
            "unavailable",
            f"{self.provider_id} unavailable after {self.policy.retries + 1} attempts "
            f"({last_error}); no usable cached data",
        )

    def invalidate(self, url: str, params: Mapping[str, str] | None = None) -> None:
        """Remove a response that a provider parser found uncacheable."""
        with self._lock:
            self._cache.pop(self._key(url, params or {}), None)


def canonical_fixture_bytes(value: Any) -> bytes:
    """Canonical JSON used by the recorder and deterministic replay checks."""

    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
