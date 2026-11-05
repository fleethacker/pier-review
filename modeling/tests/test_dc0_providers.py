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
