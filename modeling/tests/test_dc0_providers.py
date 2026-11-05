"""DC0 shared provider policy. Tests use injected clocks/transports only."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mooring.environment.errors import ProviderError
from mooring.environment.providers import (
    Available,
    BreakerState,
    EnvironmentProvider,
    FixtureProvider,
    HttpPayload,
    HttpPolicy,
    ProviderHttpClient,
    Unavailable,
    canonical_fixture_bytes,
    provider_config,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@dataclass
class Clock:
    value: datetime = T0
    sleeps: list[float] = field(default_factory=list)

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)


class FakeProvider:
    provider_id = "fake"

    def __init__(self, value):
        self.value = value

    def snapshot(self, at):
        return self.value


def assert_provider_contract(provider: EnvironmentProvider, at: datetime):
    assert provider.provider_id
    got = provider.snapshot(at)
    assert isinstance(got, (Available, Unavailable))
    if isinstance(got, Available):
        assert got.value.valid_at_utc.tzinfo is not None


def test_fake_and_fixture_providers_pass_the_same_contract():
    fixture = Path(__file__).parents[1] / "mooring/environment/fixtures/replay_sample.json"
    recorded = FixtureProvider(fixture, basis="scenario", source_kind="mock")
    good = recorded.snapshot(T0)
    assert isinstance(good, Available)
    assert good.value.source == "mock" and good.value.metadata.basis == "scenario"
    for provider in (recorded, FakeProvider(good), FakeProvider(Unavailable("OUTAGE", "down"))):
        assert isinstance(provider, EnvironmentProvider)
        assert_provider_contract(provider, T0)


def client(responses, **policy):
    clock = Clock()
    calls = []

    def transport(url, params, timeout, headers):
        calls.append((url, dict(params), timeout, dict(headers)))
        value = responses.pop(0) if len(responses) > 1 else responses[0]
        if isinstance(value, Exception):
            raise value
        return value

    return ProviderHttpClient("test", HttpPolicy(**policy), clock, transport), clock, calls


OK = HttpPayload(200, b'{"ok":true}', {})


def test_timeout_retry_exhaustion_and_descriptive_user_agent():
    c, clock, calls = client([TimeoutError("slow")], retries=2, backoff_s=1, min_interval_s=0, breaker_failures=5)
    with pytest.raises(ProviderError, match="3 attempts"):
        c.get("https://provider.invalid/data")
    assert len(calls) == 3 and clock.sleeps == [1, 2]
    assert calls[0][2] == 10 and calls[0][3]["User-Agent"] == "mooring-environment-client/0.1"


def test_cache_hit_expiry_and_stale_fallback():
    c, clock, calls = client([OK, TimeoutError("down")], retries=0, min_interval_s=0, cache_ttl_s=60, max_stale_s=300)
    assert not c.get("https://provider.invalid/data").from_cache
    clock.value += timedelta(seconds=30)
    assert c.get("https://provider.invalid/data").from_cache and len(calls) == 1
    clock.value += timedelta(seconds=60)
    stale = c.get("https://provider.invalid/data")
    assert stale.from_cache and stale.stale and stale.age_s == 90
    clock.value += timedelta(seconds=301)
    with pytest.raises(ProviderError):
        c.get("https://provider.invalid/data")


def test_recorded_retrieval_is_immutable_across_fresh_and_stale_cache_hits():
    c, clock, calls = client([OK, TimeoutError("down")], retries=0, min_interval_s=0,
                            cache_ttl_s=60, max_stale_s=300)
    first = c.get("https://provider.invalid/data")
    assert first.retrieved_at_utc == clock.value
    clock.value += timedelta(seconds=30)
    cached = c.get("https://provider.invalid/data")
    clock.value += timedelta(seconds=60)
    stale = c.get("https://provider.invalid/data")
    assert cached.from_cache and stale.stale and len(calls) == 2
    assert first.retrieved_at_utc == cached.retrieved_at_utc == stale.retrieved_at_utc
    assert first.content == cached.content == stale.content


def test_breaker_opens_short_circuits_then_half_opens_and_closes():
    c, clock, calls = client([TimeoutError("down"), OK], retries=0, min_interval_s=0, breaker_failures=1, breaker_reset_s=30)
    with pytest.raises(ProviderError):
        c.get("https://provider.invalid/data")
    assert c.breaker.state == BreakerState.OPEN
    with pytest.raises(ProviderError, match="circuit breaker"):
        c.get("https://provider.invalid/data")
    assert len(calls) == 1
    clock.value += timedelta(seconds=30)
    assert c.get("https://provider.invalid/data").json() == {"ok": True}
    assert c.breaker.state == BreakerState.CLOSED and len(calls) == 2


def test_rate_limit_and_backoff_share_the_injected_clock():
    first = HttpPayload(200, b"{}", {})
    c, clock, _ = client([first], retries=0, min_interval_s=2, cache_ttl_s=0)
    c.get("https://provider.invalid/a")
    c.get("https://provider.invalid/b")
    assert clock.sleeps == [2]


def test_canonical_fixture_replay_is_byte_identical():
    a = {"z": 2, "a": [3, {"b": 1}]}
    b = json.loads('{"a":[3,{"b":1}],"z":2}')
    assert canonical_fixture_bytes(a) == canonical_fixture_bytes(b) == b'{"a":[3,{"b":1}],"z":2}\n'


def test_provider_configuration_has_enable_flag_and_base_url(monkeypatch):
    monkeypatch.setenv("MOORING_PROVIDER_NWS_ENABLED", "true")
    monkeypatch.setenv("MOORING_PROVIDER_NWS_BASE_URL", "https://example.test/")
    assert provider_config("nws").enabled is True
    assert provider_config("nws").base_url == "https://example.test"
    monkeypatch.setenv("MOORING_PROVIDER_NWS_ENABLED", "maybe")
    with pytest.raises(ValueError, match="must be true or false"):
        provider_config("nws")


@pytest.mark.parametrize('max_stale,available', [(20, False), (100, True)])
def test_retry_time_counts_toward_stale_age_and_cutoff(max_stale, available):
    c, clock, calls = client([OK, TimeoutError('down')], retries=1, backoff_s=10,
                            min_interval_s=0, cache_ttl_s=5, max_stale_s=max_stale)
    c.get('https://provider.invalid/data')
    clock.value += timedelta(seconds=15)
    if available:
        stale = c.get('https://provider.invalid/data')
        assert stale.stale and stale.age_s == 25
    else:
        with pytest.raises(ProviderError): c.get('https://provider.invalid/data')
    assert len(calls) == 3


def test_open_breaker_can_serve_only_explicitly_stale_cache_inside_its_age_bound():
    c, clock, calls = client([OK, TimeoutError('down')], retries=0, min_interval_s=0,
        cache_ttl_s=5, max_stale_s=30, breaker_failures=1, breaker_reset_s=500)
    c.get('https://provider.invalid/data')
    clock.value += timedelta(seconds=10)
    assert c.get('https://provider.invalid/data').stale
    clock.value += timedelta(seconds=1)
    cached = c.get('https://provider.invalid/data')
    assert cached.stale and cached.age_s == 11 and len(calls) == 2
    clock.value += timedelta(seconds=20)
    with pytest.raises(ProviderError): c.get('https://provider.invalid/data')
    assert len(calls) == 2


@pytest.mark.parametrize('options', [{'timeout_s': 0}, {'timeout_s': float('nan')},
    {'backoff_s': float('inf')}, {'retries': 1.5}, {'breaker_failures': 1.5}])
def test_provider_policy_rejects_nonfinite_or_noninteger_limits(options):
    with pytest.raises(ValueError): HttpPolicy(**options)


def test_request_budget_bounds_lock_acquisition_without_starting_transport():
    c, _, calls = client([OK])
    requested = []

    class BusyLock:
        def acquire(self, *, timeout):
            requested.append(timeout)
            return False

        def release(self):
            pytest.fail("unacquired lock must not be released")

    c._lock = BusyLock()
    with pytest.raises(ProviderError, match="deadline exceeded waiting for provider lock"):
        c.get("https://provider.invalid/data", deadline_monotonic=12, monotonic=lambda: 10)
    assert requested == [2] and calls == []


def test_time_spent_queued_reduces_transport_timeout_and_releases_lock():
    c, clock, calls = client([OK], retries=0, min_interval_s=0)
    events = []

    class DelayedLock:
        def acquire(self, *, timeout):
            events.append(timeout)
            clock.value += timedelta(seconds=4)
            return True

        def release(self):
            events.append("released")

    c._lock = DelayedLock()
    payload = c.get("https://provider.invalid/data", deadline_monotonic=5,
                    monotonic=lambda: (clock.value - T0).total_seconds())
    assert payload.json() == {"ok": True}
    assert calls[0][2] == 1 and events == [5, "released"]


@pytest.mark.parametrize("wait_kind", ["rate", "backoff"])
def test_request_budget_caps_rate_and_retry_waits(wait_kind):
    c, clock, calls = client([OK if wait_kind == "rate" else TimeoutError("down")],
                             retries=1, min_interval_s=5 if wait_kind == "rate" else 0,
                             backoff_s=5, breaker_failures=10)
    if wait_kind == "rate":
        c.get("https://provider.invalid/first")
    with pytest.raises(ProviderError, match="total request deadline exceeded"):
        c.get("https://provider.invalid/second", deadline_monotonic=1,
              monotonic=lambda: (clock.value - T0).total_seconds())
    assert len(calls) == 1 and clock.sleeps == [1]


def test_transport_finishing_after_deadline_cannot_publish_or_cache_a_result():
    clock = Clock()

    def slow_transport(*_):
        clock.value += timedelta(seconds=2)
        return OK

    c = ProviderHttpClient("test", HttpPolicy(retries=0, min_interval_s=0), clock, slow_transport)
    with pytest.raises(ProviderError, match="deadline exceeded"):
        c.get("https://provider.invalid/data", deadline_monotonic=1,
              monotonic=lambda: (clock.value - T0).total_seconds())
    assert not c._cache
    # The failed request released its lock; a later caller can complete.
    c.transport = lambda *_: OK
    assert c.get("https://provider.invalid/data").json() == {"ok": True}


def test_streaming_transport_honors_shorter_remaining_caller_budget(monkeypatch):
    import httpx
    from mooring.environment.providers import bounded_httpx_transport

    class Stream:
        status_code = 200
        headers = {}

        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_bytes(self): yield b"{}"

    monkeypatch.setattr(httpx, "stream", lambda *_args, **_kwargs: Stream())
    ticks = iter([0, 0.1, 0.3])
    with pytest.raises(httpx.TimeoutException, match="0.2s elapsed limit"):
        bounded_httpx_transport("https://provider.invalid/data", {}, 0.2, {},
                                max_response_bytes=100, max_elapsed_s=5,
                                monotonic=lambda: next(ticks))
