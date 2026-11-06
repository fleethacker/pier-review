"""WebSocket channels. Message schemas are in openapi.yaml components (see `x-websockets`).

Every channel accepts `limit` (close after N server messages; 0 = run until the client disconnects).
"""

import asyncio
import hmac
import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timedelta

from mooring.environment.coops import ProviderError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from mooring import refdata
from mooring.core.schemas import (
    AnalyzeRequest,
    SimControlMessage,
    SimLifecycle,
    SimLineEventMessage,
    SimSpeedMessage,
    SimTugCommandMessage,
    TelemetryBatch,
    TelemetryRecord,
)

from .backend import env, risk, scenarios, telemetry
from .state import SESSIONS

router = APIRouter()

from mooring.core.schemas.motion_controls import SimHelmCommandMessage, SimLoadingCommandMessage, SimLineControlMessage

SimClientMessage = TypeAdapter(SimTugCommandMessage | SimLineEventMessage | SimControlMessage | SimSpeedMessage
                               | SimHelmCommandMessage | SimLoadingCommandMessage | SimLineControlMessage)


@router.websocket("/ws/env")
async def ws_env(ws: WebSocket, berth_id: str = "NAVSTA-NORFOLK-P12-N", mode: str = "live",
                 env_scenario_id: str | None = None, replay_start_utc: datetime | None = None,
                 speed: float = 1.0, interval_s: float = 1.0, limit: int = 0):
    await ws.accept()
    if mode not in {"live", "replay", "scenario"}:
        await ws.close(code=4400, reason="Environment mode must be live, replay or scenario")
        return
    if mode == "scenario" and not env_scenario_id:
        await ws.close(code=4400, reason="Scenario mode requires env_scenario_id")
        return
    if mode == "replay" and replay_start_utc is None:
        await ws.close(code=4400, reason="Replay mode requires replay_start_utc")
        return
    if (not math.isfinite(speed) or speed <= 0 or not math.isfinite(interval_s) or interval_s < 0
            or limit < 0 or (limit == 0 and interval_s == 0)):
        await ws.close(
            code=4400,
            reason="Invalid speed/interval/limit; values must be finite and an unbounded stream needs a positive interval",
        )
        return
    started = datetime.now().astimezone()
    replay_start = replay_start_utc or (started - timedelta(days=1))
    sent = 0
    try:
        while limit == 0 or sent < limit:
            if mode == "scenario" and env_scenario_id:
                snap = await asyncio.to_thread(env.scenario_snapshot, env_scenario_id, datetime.now().astimezone(), berth_id)
            elif mode == "replay":
                elapsed = (datetime.now().astimezone() - started) * speed
                snap = await asyncio.to_thread(env.replay_snapshot, berth_id, replay_start + elapsed)
            else:
                snap = await asyncio.to_thread(env.live_snapshot, berth_id)
            await ws.send_json(snap.model_dump(mode="json"))
            sent += 1
            await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        return
    except ProviderError as exc:
        await ws.send_json({"error": exc.kind, "detail": str(exc)})
        await ws.close(code=1013)
        return
    except refdata.NotFound:
        await ws.close(code=4404, reason="Environment scenario, berth or reference not found")
        return
    except refdata.InvalidReference:
        await ws.close(code=4400, reason="Invalid environment scenario or berth reference")
        return
    await ws.close()


# Alert source reads and equilibrium solves are synchronous. A separate, bounded
# pool prevents them from occupying the ASGI loop or exhausting session workers.
ALERT_TIMEOUT_S = 30.0
_ALERT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="alerts")
_ALERT_SLOTS = threading.BoundedSemaphore(4)


async def _alert_work(function, *args):
    if not _ALERT_SLOTS.acquire(blocking=False):
        raise TimeoutError("alert workers busy")
    try:
        future = _ALERT_POOL.submit(copy_context().run, function, *args)
    except BaseException:
        _ALERT_SLOTS.release()
        raise
    future.add_done_callback(lambda _: _ALERT_SLOTS.release())
    # A timed-out thread keeps its slot until it actually exits; no unbounded queue.
    return await asyncio.wait_for(asyncio.wrap_future(future), timeout=ALERT_TIMEOUT_S)


def _alert_frame(sc, berth_id, analyze_req):
    snapshot = scenarios.environment_for(sc) if sc else env.now(berth_id)
    if sc and sc.config and analyze_req is None:
        analyze_req = AnalyzeRequest(ship_class_id=sc.ship_class_id, loading=sc.loading, berth_id=sc.berth_id,
            config=sc.config, environment=snapshot, tugs=sc.tugs)
    return risk.alert_for(snapshot, analyze_req), analyze_req


@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket, berth_id: str = "NAVSTA-NORFOLK-P12-N", scenario_id: str | None = None,
                    interval_s: float = 5.0, limit: int = 0):
    import math
    from mooring import refdata

    await ws.accept()
    if not math.isfinite(interval_s) or interval_s < 0 or limit < 0 or (limit == 0 and interval_s == 0):
        await ws.close(code=4400, reason="Invalid alert interval/limit; an unbounded stream needs a positive interval")
        return
    analyze_req = None
    sent = 0
    try:
        sc = await _alert_work(scenarios.get, scenario_id) if scenario_id else None
        while limit == 0 or sent < limit:
            # Resolve the same saved source for every frame; never swap a scenario for live/mock data.
            alert, analyze_req = await _alert_work(_alert_frame, sc, berth_id, analyze_req)
            await ws.send_json(alert.model_dump(mode="json"))
            sent += 1
            if limit == 0 or sent < limit:
                await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        return
    except TimeoutError:
        await ws.close(code=1013, reason="Alert source or calculation timed out or is busy; retry later")
        return
    except ProviderError as exc:
        # No invented Alert/environment payload; the terminal close carries the provider state.
        await ws.close(code=1013, reason=f"Environment source unavailable ({exc.kind})")
        return
    except refdata.NotFound:
        await ws.close(code=4404, reason="Scenario, environment source or reference not found")
        return
    except refdata.InvalidReference:
        await ws.close(code=4400, reason="Invalid scenario or environment reference")
        return
    await ws.close()


@router.websocket("/ws/sim/{session_id}")
async def ws_sim(ws: WebSocket, session_id: str, limit: int = 0, after_sequence: int = -1):
    # This handler alone is changed; /ws/env is owned by another workstream.
    import anyio
    from mooring.core import access
    from .security import identity, AccessError
    from .sim_sessions import session_wait, session_work
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
        try:
            await session_work(session.attach,connection)
            await session_work(session.resync,after_sequence)
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
                    await session_work(session.receive,connection,msg)
                except (ValidationError,ValueError) as exc:
                    # Invalid commands close the controller; no partial application.
                    await ws.close(code=1008,reason=("Invalid command schema" if isinstance(exc,ValidationError) else str(exc))[:120])
                    return
        async def send_frames():
            # Retained lifecycle messages newer than after_sequence, then only the newest frame. A slow client
            # skips intermediate frames (sequence gaps); it never queues them and never slows physics.
            # On (re)connect the current latest frame is always sent so the client has a starting state, even if
            # its sequence <= after_sequence; consumers drop frames they already hold by (run_id, sequence).
            sent=0; last_lifecycle=after_sequence; last_frame=-1
            while limit==0 or sent<limit:
                session.changed.clear()
                for message in await session_work(session.pending_messages,last_lifecycle,last_frame):
                    await asyncio.wait_for(ws.send_json(message.model_dump(mode="json")),timeout=2.0)
                    sent+=1
                    if isinstance(message,SimLifecycle): last_lifecycle=message.sequence
                    elif message.sequence is not None: last_frame=message.sequence
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
                await session_wait(asyncio.gather(receive_task,send_task,return_exceptions=True))
        try: await ws.close()
        except RuntimeError: pass
    except asyncio.CancelledError:
        pass  # ASGI disconnect/server cancellation still performs ownership cleanup.
    finally:
        try:
            if session is not None and session.connection==connection:
                async def release_controller():
                    if ticker:
                        ticker.cancel()
                        await asyncio.gather(ticker,return_exceptions=True)
                    await session_work(session.detach,connection)
                await session_wait(asyncio.create_task(release_controller()))
        finally:
            access.principal.reset(token); access.enforced.reset(enforcement)


@router.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket, limit: int = 0):
    key = os.environ.get("MOORING_TELEMETRY_KEY")
    supplied = ws.headers.get("x-telemetry-key")
    if key and not (supplied and hmac.compare_digest(key.encode(), supplied.encode())):
        await ws.close(code=1008, reason="telemetry key required")
        return
    await ws.accept()
    sent = 0
    try:
        while limit == 0 or sent < limit:
            try:
                incoming = await ws.receive()
                if incoming["type"] == "websocket.disconnect":
                    return
                if incoming.get("text") is None:
                    await ws.close(code=1003, reason="Telemetry records must be JSON text")
                    return
                raw = json.loads(incoming["text"])
                rec = TelemetryRecord.model_validate(raw)
                ack = telemetry.ingest(TelemetryBatch(records=[rec]))
            except json.JSONDecodeError:
                ack = telemetry.TelemetryAccepted(accepted=0, rejected=1, errors=["Invalid JSON telemetry record"])
            except ValidationError as e:
                ack = telemetry.TelemetryAccepted(accepted=0, rejected=1, errors=[str(e.errors()[0]["msg"])])
            await ws.send_json(ack.model_dump(mode="json"))
            sent += 1
    except WebSocketDisconnect:
        return
    await ws.close()
