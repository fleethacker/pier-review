"""Review fix for PR #13: recorded replay served by /env/now (replay mode or the auto fallback) is never labeled
current or `good`; every component says it is not current conditions and why."""
import pytest

import mooring.environment as env
from mooring.environment import coops, live


@pytest.fixture
def network_down():
    def down(url, params, timeout):
        raise OSError("network down (simulated)")
    live.configure(coops.Fetcher(down))
    yield
    live.configure()


@pytest.mark.parametrize("mode,reason", [("auto", "live unavailable"), ("replay", "replay source selected")])
def test_recorded_fallback_is_not_labeled_current(monkeypatch, network_down, mode, reason):
    monkeypatch.setenv("MOORING_ENV_SOURCE", mode)
    snap = env.now("NAVSTA-NORFOLK-P12-N")
    assert snap.source == "replay"
    assert snap.metadata.quality != "good"
    assert snap.metadata.components, "per-component provenance expected"
    for component in snap.metadata.components:
        assert component.quality != "good"
        assert any("NOT current conditions" in item and reason in item for item in component.limitations)
