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
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
    # Per-client retention limits; operational bounds, not provider validity rules.
    cache_max_entries: int = 128
    cache_max_bytes: int = 32 * 1024 * 1024

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
        if any(type(value) is not int or value < 1 for value in (self.cache_max_entries, self.cache_max_bytes)):
            raise ValueError("provider cache entry and byte limits must be positive integers")


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
    # Recorded once at transport completion; age is not a reproducible timestamp.
    retrieved_at_utc: datetime | None = None

    def json(self) -> Any:
        try:
            return json.loads(self.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError("malformed", "provider response is not valid JSON") from None


Transport = Callable[[str, Mapping[str, str], float, Mapping[str, str]], HttpPayload]


def httpx_transport(url: str, params: Mapping[str, str], timeout_s: float, headers: Mapping[str, str]) -> HttpPayload:
    response = httpx.get(url, params=params, timeout=timeout_s, headers=headers, follow_redirects=False)
    return HttpPayload(response.status_code, response.content, dict(response.headers))


def bounded_httpx_transport(
    url: str,
    params: Mapping[str, str],
    timeout_s: float,
    headers: Mapping[str, str],
    *,
    max_response_bytes: int,
    max_elapsed_s: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> HttpPayload:
    """Stream with byte and elapsed-time caps, including slow-drip responses."""
    started = monotonic()
    elapsed_limit = min(max_elapsed_s, timeout_s)

    def ensure_elapsed_bound() -> None:
        if monotonic() - started >= elapsed_limit:
            raise httpx.TimeoutException(f"response exceeded {elapsed_limit}s elapsed limit")

    with httpx.stream(
        "GET",
        url,
        params=params,
        timeout=httpx.Timeout(timeout_s, read=min(timeout_s, 1.0)),
        headers=headers,
        follow_redirects=False,
    ) as response:
        ensure_elapsed_bound()
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > max_response_bytes:
                    raise httpx.HTTPError(f"response exceeds {max_response_bytes} bytes")
            except ValueError:
                pass
        content = bytearray()
        for chunk in response.iter_bytes():
            ensure_elapsed_bound()
            content.extend(chunk)
            if len(content) > max_response_bytes:
                raise httpx.HTTPError(f"response exceeds {max_response_bytes} bytes")
        ensure_elapsed_bound()
        return HttpPayload(response.status_code, bytes(content), dict(response.headers))


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
        self._cache: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], tuple[datetime, HttpPayload]] = OrderedDict()
        self._cache_bytes = 0
        self._last_call: datetime | None = None
        self.calls = 0

    @staticmethod
    def _key(url: str, params: Mapping[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        return url, tuple(sorted((str(k), str(v)) for k, v in params.items()))

    def _cached(self, payload: HttpPayload, *, age_s: float, stale: bool) -> HttpPayload:
        return replace(payload, from_cache=True, stale=stale, age_s=age_s)

    @staticmethod
    def _cache_size(key, payload: HttpPayload) -> int:
        # Count retained wire bytes, including request keys and response headers.
        strings = [key[0], *(value for pair in key[1] for value in pair),
                   *(value for pair in payload.headers.items() for value in pair)]
        return len(payload.content) + sum(len(value.encode("utf-8")) for value in strings)

    def _evict(self, key) -> None:
        hit = self._cache.pop(key, None)
        if hit is not None:
            self._cache_bytes -= self._cache_size(key, hit[1])

    def _prune(self, now: datetime) -> None:
        retention_s = max(self.policy.cache_ttl_s, self.policy.max_stale_s)
        for key, (retrieved, _) in list(self._cache.items()):
            if not 0 <= (now - retrieved).total_seconds() <= retention_s:
                self._evict(key)

    def _retain(self, key, retrieved: datetime, payload: HttpPayload) -> None:
        self._prune(retrieved)
        self._evict(key)
        size = self._cache_size(key, payload)
        if size > self.policy.cache_max_bytes:
            return  # A successful oversized response is usable, but not retained.
        while self._cache and (len(self._cache) >= self.policy.cache_max_entries
                               or self._cache_bytes + size > self.policy.cache_max_bytes):
            self._evict(next(iter(self._cache)))
        self._cache[key] = (retrieved, payload)
        self._cache_bytes += size

    def get(
        self, url: str, params: Mapping[str, str] | None = None, *,
        deadline_monotonic: float | None = None, monotonic: Callable[[], float] = time.monotonic,
    ) -> HttpPayload:
        """Serialize provider state within an optional caller-owned elapsed budget.

        The budget includes lock contention, rate waits, retries and transport.
        Transports must honor their timeout; streaming adapters also bound total
        response elapsed time rather than only an individual socket operation.
        """
        if deadline_monotonic is not None and not math.isfinite(deadline_monotonic):
            raise ValueError("provider deadline must be finite")

        def remaining() -> float:
            budget = math.inf if deadline_monotonic is None else deadline_monotonic - monotonic()
            if budget <= 0:
                raise ProviderError("unavailable", f"{self.provider_id} total request deadline exceeded")
            return budget

        if deadline_monotonic is None:
            acquired = self._lock.acquire()
        else:
            acquired = self._lock.acquire(timeout=remaining())
        if not acquired:
            raise ProviderError("unavailable", f"{self.provider_id} total request deadline exceeded waiting for provider lock")
        try:
            remaining()
            return self._get(url, params, remaining=remaining)
        finally:
            self._lock.release()

    def _get(self, url: str, params: Mapping[str, str] | None, *, remaining: Callable[[], float]) -> HttpPayload:
        params = params or {}
        key = self._key(url, params)
        now = self.clock.now()
        self._prune(now)
        hit = self._cache.get(key)
        if hit:
            self._cache.move_to_end(key)
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
            remaining()
            if self._last_call is not None:
                wait = self.policy.min_interval_s - (self.clock.now() - self._last_call).total_seconds()
                if wait > 0:
                    self.clock.sleep(min(wait, remaining()))
                    remaining()
            self._last_call = self.clock.now()
            self.calls += 1
            try:
                payload = self.transport(
                    url,
                    params,
                    min(self.policy.timeout_s, remaining()),
                    {"User-Agent": self.user_agent, "Accept": "application/json"},
                )
            except (httpx.HTTPError, OSError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                remaining()
                if payload.status_code == 429 or payload.status_code >= 500:
                    last_error = f"HTTP {payload.status_code}"
                else:
                    self.breaker.succeeded()
                    if 200 <= payload.status_code < 300:
                        retrieved = self.clock.now().astimezone(UTC)
                        payload = replace(payload, retrieved_at_utc=retrieved)
                        self._retain(key, retrieved, payload)
                    return payload
            remaining()
            if attempt < self.policy.retries:
                self.clock.sleep(min(self.policy.backoff_s * (2**attempt), remaining()))
                remaining()

        remaining()
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
            self._evict(self._key(url, params or {}))


def canonical_fixture_bytes(value: Any) -> bytes:
    """Canonical JSON used by the recorder and deterministic replay checks."""

    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
