"""Provider-to-planner and asynchronous channel regressions, entirely offline."""

import asyncio
import json
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from modeling_api.main import app
from modeling_api.security import FORECAST_PATHS
from mooring import refdata
from mooring.core.schemas.forecast_planning import ForecastResolveRequest
from mooring.environment.composed_forecast import ForecastComposer
from mooring.environment.coops import Fetcher
from mooring.moored.forecast_resolver import resolve_forecast
from test_d2_composed_forecast import AS_OF, BERTH, FixtureNWS, prediction_transport, request


def native_prediction_transport(url, params, timeout):
    """Expand the hourly synthetic fixture to native six-minute prediction times."""
    status, body = prediction_transport()(url, params, timeout)
    document = json.loads(body)
    current = params["product"] == "currents_predictions"
    hourly = document["current_predictions"]["cp"] if current else document["predictions"]
    from datetime import UTC, datetime
    rows = []
    for row in hourly[:-1]:
        key = "Time" if current else "t"
        at = datetime.strptime(row[key], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        rows.extend(row | {key: (at + timedelta(minutes=6*i)).strftime("%Y-%m-%d %H:%M")}
                    for i in range(10))
    rows.append(hourly[-1])
    return status, json.dumps({"current_predictions": {"cp": rows}} if current else {"predictions": rows})


@pytest.mark.parametrize("start_hours,count", [(24, 961), (0, 1201)])
def test_native_forecast_reaches_planner_without_discarding_knots(monkeypatch, start_hours, count):
    monkeypatch.delenv("MOORING_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("MOORING_MAX_FORECAST_BODY_BYTES", raising=False)
    req = request(horizon_start_utc=AS_OF+timedelta(hours=start_hours),
                  horizon_end_utc=AS_OF+timedelta(hours=120))
    composer = ForecastComposer(nws=FixtureNWS(), clock=lambda: AS_OF,
        coops_fetcher=Fetcher(native_prediction_transport, clock=lambda: AS_OF,
                              retries=0, min_interval_s=0))
    composed = composer.compose(req)
    assert composed.manifest.status == "complete"
    assert len(composed.snapshots) == count
    resolve = ForecastResolveRequest(berth_id=BERTH, as_of_utc=AS_OF,
        from_utc=req.horizon_start_utc, to_utc=req.horizon_end_utc, forecast=composed.snapshots,
        forecast_binding={"source": "supplied", "revision": composed.manifest.revision})
    body = resolve.model_dump_json()
    assert 1024*1024 < len(body.encode()) < 4*1024*1024
    with TestClient(app) as client:
        response = client.post("/api/v1/mooring/forecast/resolve", content=body,
                               headers={"content-type": "application/json"})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["coverage_complete"]
    assert len(result["series"]) == count
    expected = [s.model_dump(mode="json") for s in composed.snapshots]
    for snapshot in expected:
        snapshot["metadata"]["components"].sort(key=lambda component: component["component"])
    assert result["series"] == expected  # resolver canonicalizes provenance order only
    assert response.json()["validity"]["state"] == "limited"
    assert result["forecast_manifest"]["revision"] == composed.manifest.revision
    if count == 1201:
        oversized = composed.snapshots + [composed.snapshots[-1]]
        with pytest.raises(ValidationError, match="1201"):
            ForecastResolveRequest.model_validate(resolve.model_dump() | {"forecast": oversized})
        with pytest.raises(refdata.InvalidReference, match="1201"):
            resolve_forecast(oversized, as_of_utc=AS_OF,
                             from_utc=req.horizon_start_utc, to_utc=req.horizon_end_utc)


@pytest.mark.parametrize("path", sorted(FORECAST_PATHS))
def test_forecast_body_limits_remain_bounded_and_respect_configuration(monkeypatch, path):
    monkeypatch.delenv("MOORING_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("MOORING_MAX_FORECAST_BODY_BYTES", raising=False)
    with TestClient(app) as client:
        assert client.post(path, content=b"x" * (4*1024*1024+1)).status_code == 413
        assert client.post("/api/v1/scenarios", content=b"x" * (1024*1024+1)).status_code == 413
        monkeypatch.setenv("MOORING_MAX_BODY_BYTES", "10")
        assert client.post(path, content=b"x"*11).status_code == 413
        monkeypatch.setenv("MOORING_MAX_FORECAST_BODY_BYTES", "20")
        assert client.post(path, content=b"x"*21).status_code == 413
        assert client.post(path, content=b"x"*11).status_code == 422  # parsing, not the body cap
        monkeypatch.setenv("MOORING_MAX_FORECAST_BODY_BYTES", "bad")
        assert client.post(path, content=b"{}").status_code == 503


@pytest.mark.parametrize("mode,function", [
    ("live", "live_snapshot"), ("replay", "replay_snapshot"), ("scenario", "scenario_snapshot"),
])
def test_environment_fetch_does_not_block_websocket_event_loop(monkeypatch, mode, function):
    from modeling_api import ws
    from mooring.core.schemas import EnvironmentSnapshot

    snapshot = EnvironmentSnapshot(valid_at_utc=AS_OF, source="scenario", wind_speed_kt=10,
        wind_gust_kt=15, wind_from_true_deg=90, current_speed_kt=0,
        current_set_true_deg=0, water_level_mllw_ft=0)
    entered, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def blocked_provider(*args):
        assert threading.get_ident() != loop_thread, "provider I/O ran on the event loop"
        entered.set()
        assert release.wait(timeout=5), "event loop could not release the provider"
        return snapshot

    class Socket:
        frames = []
        closed = False

        async def accept(self): pass
        async def send_json(self, value): self.frames.append(value)
        async def close(self): self.closed = True

    monkeypatch.setattr(ws.env, function, blocked_provider)

    async def exercise():
        socket = Socket()
        task = asyncio.create_task(ws.ws_env(socket, mode=mode, env_scenario_id="test",
            replay_start_utc=AS_OF, interval_s=0, limit=1))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert not socket.frames
            # This coroutine must run while provider I/O is blocked. No timing assertion or sleep.
            release.set()
            await asyncio.wait_for(task, timeout=5)
            assert socket.frames == [snapshot.model_dump(mode="json")]
            assert socket.closed
        finally:
            release.set()
            if not task.done():
                await task

    asyncio.run(exercise())
