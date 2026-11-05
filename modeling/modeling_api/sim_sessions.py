"""Single-owner interactive sessions. Only the scheduler advances physics.

Disconnected/paused sessions freeze. Reconnect resumes from the same state only
on an explicit resume command; there is no wall-clock catch-up across disconnect.
Output is a latest-frame slot, so a slow socket cannot queue unbounded history.
"""
import asyncio
import json
import logging
import math
import os
import threading
import time
from collections import deque

from mooring.berthing import rich
from mooring.core import access
from mooring.core.envelopes import new_id
from mooring.core.schemas import (MotionProvenance, SimLifecycle, SimRecording, SimRecordingSummary,
                                  SimSamplingPolicy, SimScene, Validity, ValidityReason)
from mooring.core.store import DocStore
from .backend import berthing_sim
from .state import API_PREFIX

log = logging.getLogger(__name__)

LIFECYCLE_LOG = 256         # lifecycle messages retained for reconnect
RECORDING_FRAMES = 10000    # SimRecording.frames maximum
RECORDING_LIFECYCLE = 1000  # SimRecording.lifecycle maximum
# Recorded frames are kept as compact JSON (about 12-15 KB each), never as model objects (~70 KB each).
RECORDING_MAX_BYTES = int(os.environ.get("MOORING_RECORDING_MAX_BYTES", str(32 * 1024 * 1024)))
PUBLISH_MIN_S = 0.05        # display frames at most 20 per wall second; physics is never decimated
PERSIST_MIN_S = 2.0         # pause/reset persistence is throttled; detach/end/error always persist
MIN_TICK_S = 0.005          # scheduler sleep floor, so tiny physics steps cannot spin the event loop
MAX_STEPS_PER_TICK = 2000   # bounded work per tick; falling behind is reported as lag, never skipped
RUNTIME_STEPS_PER_TICK = 10 # actual accepted integration segments plus command applications, not nominal dt intervals
LAG_ALERT_S = 1.0
RECORDINGS = DocStore("simulation_recordings", SimRecording)
SCENES = DocStore("simulation_scenes", SimScene)
RECORDING_INDEX = DocStore("simulation_recording_index", SimRecordingSummary)


def _compact(model) -> str:
    return json.dumps(model.model_dump(mode="json"), separators=(",", ":"), allow_nan=False)


async def session_work(function, *args, **kwargs):
    """Join a worker before propagating cancellation, even while it waits for the session lock.

    Cancelling a to_thread await does not cancel its thread. Repeated task cancellations
    must not abandon an attach, command or detach that could later mutate a new controller's state.
    """
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    return await session_wait(work)


async def session_wait(work):
    """Finish owned work before propagating cancellation; cleanup can itself be cancelled repeatedly."""
    import anyio
    cancellation = None
    with anyio.CancelScope(shield=True):
        while True:
            try:
                result = await asyncio.shield(work)
            except asyncio.CancelledError as exc:
                if work.cancelled():
                    raise
                cancellation = exc
            except Exception:
                if cancellation is not None:
                    raise cancellation from None
                raise
            else:
                break
    if cancellation is not None:
        raise cancellation
    return result


def store_recording_json(session_id: str, raw: str) -> None:
    """Persist already-validated recording JSON without re-validating thousands of frames."""
    from mooring.core.access import claim
    from mooring.core.store import db
    claim(RECORDINGS.namespace, session_id)
    d = db()
    with d.lock:
        d.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?)", (RECORDINGS.namespace, session_id, raw))


def load_recording_json(session_id: str) -> str:
    from mooring.core.access import allowed
    from mooring.core.store import db
    if not allowed(RECORDINGS.namespace, session_id): raise KeyError(session_id)
    rows = db().execute("SELECT body FROM docs WHERE namespace=? AND key=?", (RECORDINGS.namespace, session_id))
    if not rows: raise KeyError(session_id)
    return rows[0][0]


def list_recordings(limit=20, after_session_id=""):
    """Bounded keyset page; filter ownership in SQL before reading document bodies."""
    from mooring.core.store import db
    query = "SELECT d.key,d.body FROM docs d WHERE d.namespace=? AND d.key>?"
    params = [RECORDING_INDEX.namespace, after_session_id]
    if access.enforced.get():
        query += " AND EXISTS (SELECT 1 FROM ownership o WHERE o.kind=d.namespace AND o.key=d.key AND o.principal=?)"
        params.append(access.principal.get())
    rows = db().execute(query + " ORDER BY d.key LIMIT ?", (*params, limit + 1))
    return ([SimRecordingSummary.model_validate_json(row[1]) for row in rows[:limit]],
            rows[limit - 1][0] if len(rows) > limit else None)


class Session:
    """`session_id=None` is the legacy mode: unsequenced legacy frames, no lifecycle, no recording.

    With a session_id the session speaks rm0-v1: one session-wide sequence shared by frames and lifecycle
    messages, a run_id that changes on reset, a static scene, speed control and a bounded recording.
    Display frames are decimated in wall time; recorded frames are sampled at exact simulation-time
    boundaries inside integration, so neither depends on tick timing or speed.
    """

    def __init__(self, model, *, session_id=None, clock=time.monotonic, record_interval_s=1.0):
        self.model,self.clock,self.session_id=model,clock,session_id
        self.rich=session_id is not None
        self.initial=(model.sc.model_copy(deep=True),model.initial.model_copy(deep=True),model.env.model_copy(deep=True))
        self.lock=threading.RLock()
        self.connection=None
        self.paused=False
        self.speed=1.0
        self.anchor_wall=clock()
        self.anchor_sim=0.0
        self.lag_s=0.0
        self.changed=asyncio.Event()
        self.event_loop=None
        self.last_access=clock()
        self.received=0
        self.window_start=clock()
        self.error=None
        self.state="created"
        self.sequence=-1
        self.lifecycle=deque(maxlen=LIFECYCLE_LOG)
        self.lifecycle_evicted_through=-1
        self.record_interval_s=record_interval_s
        self.rec_frames,self.rec_lifecycle,self.rec_run_end=[],[],{}
        self.rec_bytes=0; self.rec_last_t=None
        self.rec_frames_truncated=self.rec_lifecycle_truncated=False
        self.rec_failure=None
        self.rec_dirty=False; self.last_persist_wall=-math.inf
        self.rec_validity=None
        self.rec_reasons={}
        self.next_record_t=0.0
        self.last_publish_wall=-math.inf; self.last_alerts=None
        self.latest=None
        if self.rich:
            self.run_id=new_id("run")
            self.scene=rich.build_scene(model)
            self.emit("created")
        else:
            self.run_id=self.scene=None
        self.publish()
        self.record_now()

    # ---- sequence, frames, lifecycle, recording ----

    def next_sequence(self):
        self.sequence+=1
        return self.sequence

    def notify(self):
        # Session mutations run in workers; asyncio.Event itself is not thread-safe.
        if self.event_loop is not None and self.event_loop.is_running():
            self.event_loop.call_soon_threadsafe(self.changed.set)
        else:
            self.changed.set()

    def remember_validity(self, validity):
        """Only retained messages contribute; reset never erases historical failure evidence."""
        state = validity.state if validity is not None else "unknown"
        rank = {"valid": 0, "limited": 1, "unknown": 2, "invalid": 3}
        if self.rec_validity is None or rank[state] > rank[self.rec_validity]:
            self.rec_validity = state
        for reason in validity.reasons if validity is not None else []:
            self.rec_reasons[_compact(reason)] = reason.model_copy(deep=True)

    def make_frame(self, state=None, t=None, alerts=None):
        if self.error: alerts=[*(alerts or []), self.error]
        if not self.rich: return self.model.frame(state, t, alerts)
        return rich.rich_frame(self.model,session_id=self.session_id,run_id=self.run_id,
            sequence=self.next_sequence(),scene=self.scene,state=state,t=t,alerts=alerts)

    def publish(self, alerts=None):
        """New latest display frame. Its sequence is assigned here, before any display decimation."""
        self.latest=self.make_frame(alerts=alerts)
        self.last_publish_wall=self.clock(); self.last_alerts=alerts

    def emit(self, state, message=None):
        if not self.rich: return
        self.state=state
        item=SimLifecycle(session_id=self.session_id,run_id=self.run_id,sequence=self.next_sequence(),t_s=self.model.t,
            state=state,scene_id=self.scene.scene_id,scene_revision=self.scene.revision,message=message,
            validity=self.model.validity(),provenance=self.provenance(),speed=self.speed)
        if len(self.lifecycle)==self.lifecycle.maxlen: self.lifecycle_evicted_through=self.lifecycle[0].sequence
        self.lifecycle.append(item)
        if not self.rec_lifecycle_truncated:
            if len(self.rec_lifecycle)>=RECORDING_LIFECYCLE:
                self.rec_lifecycle_truncated=True
                self.rec_dirty=True  # truncation changes the persisted recording and its index, without a new event
            else:
                self.rec_lifecycle.append(_compact(item)); self.rec_dirty=True
                self.remember_validity(item.validity)
        self.notify()

    def resync(self, after_sequence):
        """A reconnecting client that missed evicted lifecycle history gets an explicit restatement, never silence."""
        with self.lock:
            if self.rich and after_sequence<self.lifecycle_evicted_through:
                self.emit(self.state, f"Lifecycle messages through sequence {self.lifecycle_evicted_through} are no longer "
                                      "retained; this message restates the current session state.")

    @staticmethod
    def provenance():
        return MotionProvenance(kind="estimated",source="mooring.berthing session scheduler",
            notes=["Synthetic unqualified vessel dynamics; display recording, not a qualified record."])

    def record_frame(self, frame):
        if not self.rich or self.rec_frames_truncated: return
        raw=_compact(frame)
        if len(self.rec_frames)>=RECORDING_FRAMES or self.rec_bytes+len(raw)>RECORDING_MAX_BYTES:
            self.rec_frames_truncated=True; self.rec_dirty=True; return
        self.rec_frames.append(raw); self.rec_bytes+=len(raw)
        self.remember_validity(frame.validity)
        self.rec_run_end[frame.run_id]=frame.t_s; self.rec_last_t=frame.t_s
        self.rec_dirty=True

    def record_now(self):
        """Record the current state (run start, end) if not already recorded at this time."""
        if not self.rich or (self.model.pending and self.model.pending[0][0]<=self.model.t+1e-9): return
        if self.rec_last_t is None or self.rec_last_t<self.model.t-1e-9:
            # Commands can change forces/lines without changing time; a cached display frame can be stale.
            self.record_frame(self.make_frame())
        self.next_record_t=(math.floor((self.model.t+1e-9)/self.record_interval_s)+1)*self.record_interval_s

    def observe(self, t0, s0, t1, s1):
        """Integration hook: record exact simulation-time samples inside the step, independent of tick timing."""
        while not self.rec_frames_truncated and self.next_record_t<t1-1e-9:
            t=self.next_record_t
            try:
                self.record_frame(self.make_frame(self.model.integrator.sample(t),t))
            except Exception as exc:  # noqa: BLE001 - a recording fault must not masquerade as a dynamics failure
                log.exception("recording sample failed for %s",self.session_id)
                self.rec_failure=str(exc)[:300]; self.rec_frames_truncated=True; self.rec_dirty=True
            self.next_record_t+=self.record_interval_s

    def recording_parts(self):
        with self.lock:
            if not self.rich or not self.rec_frames: raise ValueError("session has no recording")
            reasons=list(self.rec_reasons.values())
            if self.rec_frames_truncated or self.rec_lifecycle_truncated:
                reasons.append(ValidityReason(code="RECORDING_TRUNCATED",
                    message=f"Recording stopped at {len(self.rec_frames)} frames ({self.rec_bytes} bytes) / "
                            f"{len(self.rec_lifecycle)} lifecycle messages"
                            + (f" after a sampling failure: {self.rec_failure}" if self.rec_failure else "")
                            + "; the live display continued."))
            head={"schema_version":"rm0-v1","recording_id":f"rec_{self.session_id}","session_id":self.session_id,
                  "scene_id":self.scene.scene_id,"scene_revision":self.scene.revision,
                  # Simulated time summed over runs (reset starts a new run); paused wall time is excluded.
                  "duration_s":sum(self.rec_run_end.values()),
                  "sampling":SimSamplingPolicy(physics_dt_s=self.model.dt,display_interval_s=self.record_interval_s,
                                               max_pending_frames=1).model_dump(mode="json"),
                  "validity":Validity(state=self.rec_validity or "unknown",reasons=reasons).model_dump(mode="json"),
                  "provenance":self.provenance().model_dump(mode="json")}
            return head,list(self.rec_frames),list(self.rec_lifecycle)

    def recording_json(self):
        head,frames,lifecycle=self.recording_parts()
        h=json.dumps(head,separators=(",",":"),allow_nan=False)
        return h[:-1]+',"frames":['+",".join(frames)+'],"lifecycle":['+",".join(lifecycle)+']}'

    def recording(self):
        return SimRecording.model_validate_json(self.recording_json())

    def persist(self, force=False):
        """Keep the recording past session expiry. Storage failure is logged and retried, never reported as success."""
        if not self.rich: return
        with self.lock:
            if not self.rec_dirty or not self.rec_frames: return
            now=self.clock()
            if not force and now-self.last_persist_wall<PERSIST_MIN_S: return  # stays dirty for the next persist
            raw=self.recording_json()
            head, frames, _ = self.recording_parts()
            summary=SimRecordingSummary(**{name: head[name] for name in
                ("recording_id", "session_id", "scene_id", "scene_revision", "duration_s", "validity")},
                frame_count=len(frames), scene_url=f"{API_PREFIX}/berthing/sessions/{self.session_id}/scene",
                recording_url=f"{API_PREFIX}/berthing/sessions/{self.session_id}/recording")
            self.rec_dirty=False; self.last_persist_wall=now
        try:
            # Geometry is immutable for the session, even across reset. Save it before making the record discoverable.
            if self.session_id in SCENES:
                if SCENES[self.session_id] != self.scene:
                    raise ValueError("the recording's immutable scene changed")
            else:
                SCENES[self.session_id]=self.scene
            store_recording_json(self.session_id,raw)
            RECORDING_INDEX[self.session_id]=summary
        except Exception:  # noqa: BLE001 - persistence must not break the live session
            log.exception("could not persist recording for %s",self.session_id)
            with self.lock: self.rec_dirty=True

    def pending_messages(self, last_lifecycle, last_frame):
        """Lifecycle messages and the latest frame newer than the given sequences, in sequence order."""
        with self.lock:
            out=[m for m in self.lifecycle if m.sequence>last_lifecycle]
            frame=self.latest
            if frame is not None and (frame.sequence is None or frame.sequence>last_frame): out.append(frame)
            if self.rich: out.sort(key=lambda m: m.sequence)
            return out

    # ---- control ----

    def tick_period(self):
        return min(0.05,max(MIN_TICK_S,self.model.dt))

    def reanchor(self):
        self.anchor_wall=self.clock(); self.anchor_sim=self.model.t; self.lag_s=0.0

    def scheduled_time(self, now):
        return min(self.model.duration, self.anchor_sim + max(0, now-self.anchor_wall)*self.speed)

    def attach(self, connection):
        with self.lock:
            if self.connection is not None: raise ValueError("session already has an active controller")
            self.connection=connection
            self.changed=asyncio.Event()
            self.reanchor()
            self.last_access=self.clock()
            if not self.paused and self.state=="created": self.emit("running")

    def detach(self, connection):
        with self.lock:
            if self.connection==connection:
                self.connection=None
                self.paused=True
                self.reanchor()
                self.last_access=self.clock()
                if self.state in ("created","running"): self.emit("paused")
                self.persist(force=True)

    def fail(self, code, message, exc):
        """Stop advancing with an explicit error frame and lifecycle message; each step is guarded."""
        with self.lock:
            self._fail(code, message, exc)

    def _fail(self, code, message, exc):
        self.model.invalid=True
        self.model.reasons.append(ValidityReason(code=code,message=str(exc)[:500] or code))
        self.error=message
        try: self.publish()
        except Exception: log.exception("error frame failed for %s",self.session_id)  # keep the last good frame
        try: self.emit("error",f"{message} ({exc})"[:1000])
        except Exception: log.exception("error lifecycle failed for %s",self.session_id)
        self.persist(force=True)
        self.notify()

    def tick(self, *, max_steps=MAX_STEPS_PER_TICK):
        with self.lock:
            if self.connection is None or self.paused or self.error: return
            dt=self.model.dt
            demand=self.scheduled_time(self.clock())
            wanted=(self.model.duration if demand>=self.model.duration-1e-9
                    else math.floor((demand+1e-9)/dt)*dt)
            # Keep catch-up targets on the original grid even after a command/contact yield inside a step.
            # The actual work limit below also counts command applications and contact subdivisions.
            cap_steps=min(max_steps,max(10,math.ceil(10*self.speed),math.ceil(2*self.speed*self.tick_period()/dt)))
            # A pause/reconnect can reanchor at an off-grid yield. Drain due work at the current
            # time even when rounding newly earned clock demand down gives an earlier grid point.
            target=max(self.model.t,min(wanted,(math.floor((self.model.t+1e-9)/dt)+cap_steps)*dt))
            self.lag_s=max(0.0,wanted-target)/self.speed  # wall seconds the scheduler is behind; never skipped
            due=self.model.pending and self.model.pending[0][0]<=self.model.t+1e-9
            if target<=self.model.t+1e-9 and not due: return
            try:
                self.model.advance(target,observe=self.observe if self.rich else (lambda *args: None), max_work=max_steps)
            except (ValueError,OverflowError) as exc:
                self.fail("FORCING_UNCOVERED" if isinstance(exc,berthing_sim.ForcingUncovered) else "DYNAMICS_INTEGRATION_FAILED","Integration stopped; reset or create a new session.",exc); return
            self.lag_s=max(0.0,wanted-self.model.t)/self.speed
            alerts=[f"Simulation lagging wall clock by {self.lag_s:.1f} s at {self.speed:g}x"] if self.lag_s>LAG_ALERT_S else None
            if self.model.pending and self.model.pending[0][0]<=self.model.t+1e-9:
                # Never record a time-boundary sample halfway through its ordered commands. Lag still gets
                # lifecycle notification while command-only chunks finish that boundary.
                if alerts and alerts!=self.last_alerts:
                    self.emit(self.state,alerts[0]); self.last_alerts=alerts
                return
            try:
                ended=self.model.t>=self.model.duration-1e-9
                # Alert changes (lag appearing or clearing) are shown at once; otherwise display is wall-time decimated.
                published=(ended or not self.rich or alerts!=self.last_alerts
                           or self.clock()-self.last_publish_wall>=PUBLISH_MIN_S)
                if published: self.publish(alerts)
                if self.rich and self.next_record_t<=self.model.t+1e-9:
                    self.record_now()   # exact boundary at the end of this advance, after commands applied
                if ended and self.state!="ended":
                    self.record_now(); self.emit("ended"); self.persist(force=True)
            except Exception as exc:  # noqa: BLE001 - frame production faults are not integration faults
                self.fail("FRAME_PRODUCTION_FAILED","Frame production failed; reset or create a new session.",exc); return
            if published: self.notify()

    def receive(self, connection, msg):
        with self.lock:
            if connection!=self.connection: raise ValueError("not the active session controller")
            now=self.clock()
            if now-self.window_start>=1:
                self.window_start,self.received=now,0
            self.received+=1
            if self.received>100: raise ValueError("session command rate limit exceeded")
            self.last_access=now
            if msg.type in ("pause","resume","reset"):
                if msg.type=="reset":
                    self.model=berthing_sim.BerthingModel(*self.initial,dt=self.model.dt,duration=self.model.duration,forcing=self.model.forcing_spec)
                    self.paused=True; self.error=None
                    self.reanchor()
                    if self.rich:
                        self.run_id=new_id("run"); self.rec_last_t=None
                        self.emit("reset")
                    self.publish(); self.record_now(); self.persist()
                    self.notify()
                    return
                elif msg.type=="pause":
                    if self.paused: return
                    self.paused=True
                elif not self.error:
                    if not self.paused: return
                    self.paused=False
                self.reanchor()
                if msg.type=="pause" and self.state in ("created","running"): self.emit("paused")
                elif msg.type=="resume" and not self.error and self.state in ("created","paused","reset"): self.emit("running")
                self.publish()
                if msg.type=="pause": self.persist()
                self.notify()
            elif msg.type=="set_speed":
                if float(msg.speed)==self.speed: return
                # Preserve demand accumulated at the previous speed, including fractional steps and lag.
                self.anchor_sim=self.model.t if self.paused or self.error else self.scheduled_time(now)
                self.anchor_wall=now
                self.speed=float(msg.speed)
                self.emit(self.state,self.error if self.state=="error" else None)
                self.notify()
            else:
                # Omitted timestamp targets the next boundary. Explicit times are
                # ordered by timestamp then arrival sequence, never retroactive.
                if msg.t_s is None:
                    msg=msg.model_copy(update={"t_s":min(self.model.duration,self.model.t+self.model.dt)})
                self.model.schedule(msg)

    async def run(self):
        self.event_loop=asyncio.get_running_loop()
        while self.connection is not None:
            try:
                await session_work(self.tick, max_steps=RUNTIME_STEPS_PER_TICK)
            except Exception as exc:  # noqa: BLE001 - the ticker must never die silently
                log.exception("session scheduler failed for %s",self.session_id)
                await session_work(self.fail,"SESSION_SCHEDULER_FAILED","Session scheduler failed; reset or create a new session.",exc)
            await asyncio.sleep(self.tick_period())


_CREATE_LOCK = threading.Lock()

def create(sessions, sid, model, record_interval_s=1.0):
    with _CREATE_LOCK:
        return _create(sessions, sid, model, record_interval_s)

def _create(sessions, sid, model, record_interval_s=1.0):
    # Bounded global storage; expire only disconnected sessions after idle TTL.
    now=time.monotonic()
    ttl=float(os.environ.get("MOORING_SESSION_IDLE_S","1800"))
    for key,session in list(sessions.items()):
        if isinstance(session,Session) and session.connection is None and now-session.last_access>ttl:
            del sessions[key]
    maximum=int(os.environ.get("MOORING_MAX_SESSIONS","32"))
    per_owner=int(os.environ.get("MOORING_SESSIONS_PER_PRINCIPAL","4"))
    owned=sum(access.allowed("session",key) for key in sessions)
    if len(sessions)>=maximum or owned>=per_owner:
        from mooring.core.jobs import JobQueueFull
        raise JobQueueFull()
    access.claim("session",sid)
    sessions[sid]=Session(model,session_id=sid,record_interval_s=record_interval_s)
    return sessions[sid]
