"""WebSocket channels. Message schemas are in openapi.yaml components (see `x-websockets`).

Every channel accepts `limit` (close after N server messages; 0 = run until the client disconnects).
"""

import asyncio
import hmac
import os
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
                try:
                    snap = env.replay_snapshot(berth_id, replay_start + elapsed)
                except ProviderError as e:
                    await ws.send_json({"error": e.kind, "detail": str(e)})
                    await ws.close(code=1013)
                    return
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
    # This handler alone is changed; /ws/env is owned by another workstream.
    import anyio
    from mooring.core import access
    from .security import identity, AccessError
    from mooring.core.envelopes import new_id
    try:
        principal, enabled = identity(ws.headers)
    except AccessError as exc:
        await ws.close(code=4401, reason=exc.message)
        return
    token=access.principal.set(principal)
    enforcement=access.enforced.set(enabled)
    connection=new_id("controller")
    session=None
    ticker=None
    try:
        if not access.allowed("session",session_id) or session_id not in SESSIONS:
            await ws.close(code=4404,reason="Session not found")
            return
        session=SESSIONS[session_id]
        try: session.attach(connection)
        except ValueError:
            await ws.close(code=4409,reason="Session already controlled")
            return
        await ws.accept()
        ticker=asyncio.create_task(session.run())
        async def receive_commands():
            while True:
                incoming=await ws.receive()
                if incoming["type"]=="websocket.disconnect": return
                text=incoming.get("text")
                if text is None:
                    await ws.close(code=1003,reason="Simulation commands must be JSON text")
                    return
                if len(text.encode())>8192:
                    await ws.close(code=1009,reason="Command too large")
                    return
                try:
                    msg=SimClientMessage.validate_json(text)
                    session.receive(connection,msg)
                except (ValidationError,ValueError) as exc:
                    # Invalid commands close the controller; no partial application.
                    await ws.close(code=1008,reason=("Invalid command schema" if isinstance(exc,ValidationError) else str(exc))[:120])
                    return
        async def send_frames():
            sent=0
            while limit==0 or sent<limit:
                session.changed.clear()
                frame=session.latest
                await asyncio.wait_for(ws.send_json(frame.model_dump(mode="json")),timeout=2.0)
                sent+=1
                if limit and sent>=limit: return
                await session.changed.wait()
        receive_task=asyncio.create_task(receive_commands())
        send_task=asyncio.create_task(send_frames())
        try:
            done,pending=await asyncio.wait([receive_task,send_task],return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try: task.result()
                except TimeoutError:
                    await ws.close(code=1013,reason="Simulation client did not accept a frame within 2 seconds")
                except (WebSocketDisconnect,RuntimeError): pass
        finally:
            for task in (receive_task,send_task): task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(receive_task,send_task,return_exceptions=True)
        try: await ws.close()
        except RuntimeError: pass
    except asyncio.CancelledError:
        pass  # ASGI disconnect/server cancellation still performs ownership cleanup.
    finally:
        if session is not None and session.connection==connection:
            session.detach(connection)
            if ticker:
                ticker.cancel()
                with anyio.CancelScope(shield=True):
                    await asyncio.gather(ticker,return_exceptions=True)
        access.principal.reset(token); access.enforced.reset(enforcement)


@router.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket, limit: int = 0):
    key = os.environ.get("MOORING_TELEMETRY_KEY")
    supplied = ws.headers.get("x-telemetry-key")
    if key and not (supplied and hmac.compare_digest(key, supplied)):
        await ws.close(code=1008, reason="telemetry key required")
        return
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
