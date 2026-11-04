"""WebSocket channels. Message schemas are in openapi.yaml components (see `x-websockets`).

Every channel accepts `limit` (close after N server messages; 0 = run until the client disconnects).
"""

import asyncio
from datetime import datetime, timedelta

from mooring.environment.coops import ProviderError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from mooring.core.schemas import (
    AnalyzeRequest,
    SimControlMessage,
    SimLineEventMessage,
    SimTugCommandMessage,
    TelemetryBatch,
    TelemetryRecord,
)

from .backend import env, risk, scenarios, telemetry
from .state import SESSIONS

router = APIRouter()

SimClientMessage = TypeAdapter(SimTugCommandMessage | SimLineEventMessage | SimControlMessage)


@router.websocket("/ws/env")
async def ws_env(ws: WebSocket, berth_id: str = "NAVSTA-NORFOLK-P12-N", mode: str = "live",
                 env_scenario_id: str | None = None, replay_start_utc: datetime | None = None,
                 speed: float = 1.0, interval_s: float = 1.0, limit: int = 0):
    await ws.accept()
    started = datetime.now().astimezone()
    replay_start = replay_start_utc or (started - timedelta(days=1))
    sent = 0
    try:
        while limit == 0 or sent < limit:
            if mode == "scenario" and env_scenario_id:
                snap = env.scenario_snapshot(env_scenario_id, datetime.now().astimezone())
            elif mode == "replay":
                elapsed = (datetime.now().astimezone() - started) * speed
                snap = env.synthetic(replay_start + elapsed, "replay")
            else:
                try:
                    snap = env.now(berth_id)
                except ProviderError as e:   # documented provider failure: tell the client and close, never synthesize
                    await ws.send_json({"error": e.kind, "detail": str(e)})
                    await ws.close(code=1013)
                    return
            await ws.send_json(snap.model_dump(mode="json"))
            sent += 1
            await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        return
    await ws.close()


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket, berth_id: str = "NAVSTA-NORFOLK-P12-N", scenario_id: str | None = None,
                    interval_s: float = 5.0, limit: int = 0):
    await ws.accept()
    analyze_req = None
    if scenario_id:
        sc = scenarios.get(scenario_id)
        berth_id = sc.berth_id
        if sc.config:
            analyze_req = AnalyzeRequest(ship_class_id=sc.ship_class_id, loading=sc.loading, berth_id=sc.berth_id,
                                         config=sc.config, environment=scenarios.environment_for(sc), tugs=sc.tugs)
    sent = 0
    try:
        while limit == 0 or sent < limit:
            alert = risk.alert_for(env.now(berth_id), analyze_req)
            await ws.send_json(alert.model_dump(mode="json"))
            sent += 1
            await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        return
    await ws.close()


@router.websocket("/ws/sim/{session_id}")
async def ws_sim(ws: WebSocket, session_id: str, limit: int = 0):
    await ws.accept()
    model = SESSIONS.get(session_id)
    if model is None:
        await ws.close(code=4404, reason=f"Session '{session_id}' not found")
        return
    initial = model.state.model_copy()
    dt, sent = 0.1, 0
    try:
        while limit == 0 or sent < limit:
            alerts: list[str] = []
            try:
                raw = await asyncio.wait_for(ws.receive_json(), timeout=dt)
                msg = SimClientMessage.validate_python(raw)
                if isinstance(msg, SimTugCommandMessage):
                    model.command(msg.tug_id, msg.force_lbf, msg.direction_rel_deg)
                elif isinstance(msg, SimControlMessage):
                    if msg.type == "reset":
                        model = SESSIONS[session_id] = type(model)(model.sc, initial, model.env)
                    else:
                        model.paused = msg.type == "pause"
                else:
                    alerts.append(f"Line {msg.line_number} {msg.event}.")
            except TimeoutError:
                pass
            except ValidationError as e:
                alerts.append(f"Ignored invalid message: {e.errors()[0]['msg']}")
            events = model.step(dt)
            alerts += [e.detail for e in events]
            await ws.send_json(model.frame(alerts).model_dump(mode="json"))
            sent += 1
    except WebSocketDisconnect:
        return
    await ws.close()


@router.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket, limit: int = 0):
    await ws.accept()
    sent = 0
    try:
        while limit == 0 or sent < limit:
            raw = await ws.receive_json()
            try:
                rec = TelemetryRecord.model_validate(raw)
                ack = telemetry.ingest(TelemetryBatch(records=[rec]))
            except ValidationError as e:
                ack = telemetry.TelemetryAccepted(accepted=0, rejected=1, errors=[str(e.errors()[0]["msg"])])
            await ws.send_json(ack.model_dump(mode="json"))
            sent += 1
    except WebSocketDisconnect:
        return
    await ws.close()
