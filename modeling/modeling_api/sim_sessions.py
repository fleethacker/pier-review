"""Single-owner interactive sessions. Only the scheduler advances physics.

Disconnected/paused sessions freeze. Reconnect resumes from the same state only
on an explicit resume command; there is no wall-clock catch-up across disconnect.
Output is a latest-frame slot, so a slow socket cannot queue unbounded history.
"""
import asyncio
import logging
import math
import os
import threading
import time
from collections import deque

from mooring.berthing import rich
from mooring.core import access
from mooring.core.envelopes import new_id
from mooring.core.schemas import (MotionProvenance, SimLifecycle, SimRecording, SimSamplingPolicy, Validity,
                                  ValidityReason)
from mooring.core.store import DocStore
from .backend import berthing_sim

log = logging.getLogger(__name__)

LIFECYCLE_LOG = 256       # lifecycle messages retained for reconnect
RECORDING_FRAMES = 10000  # SimRecording.frames maximum
RECORDING_LIFECYCLE = 1000  # SimRecording.lifecycle maximum
LAG_ALERT_S = 1.0
RECORDINGS = DocStore("simulation_recordings", SimRecording)


class Session:
    """`session_id=None` is the legacy mode: unsequenced legacy frames, no lifecycle, no recording.

    With a session_id the session speaks rm0-v1: one session-wide sequence shared by frames and lifecycle
    messages, a run_id that changes on reset, a static scene, speed control and a bounded recording.
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
        self.last_access=clock()
        self.received=0
        self.window_start=clock()
        self.error=None
        self.state="created"
        self.sequence=-1
        self.lifecycle=deque(maxlen=LIFECYCLE_LOG)
        self.record_interval_s=record_interval_s
        self.rec_frames,self.rec_lifecycle,self.rec_run_end=[],[],{}
        self.rec_full=False; self.rec_dirty=False; self.next_record_t=0.0
        if self.rich:
            self.run_id=new_id("run")
            self.scene=rich.build_scene(model)
            self.emit("created")
        else:
            self.run_id=self.scene=None
        self.latest=None
        self.publish()

    # ---- sequence, frames, lifecycle, recording ----

    def next_sequence(self):
        self.sequence+=1
        return self.sequence

    def publish(self, alerts=None):
        """New latest frame. The sequence is assigned here, before any display decimation."""
        if not self.rich:
            self.latest=self.model.frame(alerts=alerts); return
        self.latest=rich.rich_frame(self.model,session_id=self.session_id,run_id=self.run_id,
            sequence=self.next_sequence(),scene=self.scene,alerts=alerts)
        t=self.latest.t_s
        if t>=self.next_record_t-1e-9:
            self.record_frame(self.latest)
            self.next_record_t=(math.floor((t+1e-9)/self.record_interval_s)+1)*self.record_interval_s

    def emit(self, state, message=None):
        if not self.rich: return
        self.state=state
        validity=self.model.validity()
        item=SimLifecycle(session_id=self.session_id,run_id=self.run_id,sequence=self.next_sequence(),t_s=self.model.t,
            state=state,scene_id=self.scene.scene_id,scene_revision=self.scene.revision,message=message,
            validity=validity,provenance=self.provenance(),speed=self.speed)
        self.lifecycle.append(item)
        if not self.rec_full:
            if len(self.rec_lifecycle)>=RECORDING_LIFECYCLE: self.rec_full=True
            else: self.rec_lifecycle.append(item)
        self.rec_dirty=True
        self.changed.set()

    @staticmethod
    def provenance():
        return MotionProvenance(kind="estimated",source="mooring.berthing session scheduler",
            notes=["Synthetic unqualified vessel dynamics; display recording, not a qualified record."])

    def record_frame(self, frame):
        if self.rec_full: return
        if len(self.rec_frames)>=RECORDING_FRAMES:
            self.rec_full=True; return
        self.rec_frames.append(frame)
        self.rec_run_end[frame.run_id]=frame.t_s
        self.rec_dirty=True

    def recording(self):
        with self.lock:
            if not self.rich or not self.rec_frames: raise ValueError("session has no recording")
            validity=self.model.validity()
            reasons=list(validity.reasons)
            if self.rec_full:
                reasons.append(ValidityReason(code="RECORDING_TRUNCATED",
                    message=f"Recording stopped at {len(self.rec_frames)} frames / {len(self.rec_lifecycle)} lifecycle messages; "
                            "the live display continued."))
            validity=Validity(state=validity.state,reasons=reasons)
            return SimRecording(recording_id=f"rec_{self.session_id}",session_id=self.session_id,
                scene_id=self.scene.scene_id,scene_revision=self.scene.revision,duration_s=sum(self.rec_run_end.values()),
                sampling=SimSamplingPolicy(physics_dt_s=self.model.dt,display_interval_s=self.record_interval_s,max_pending_frames=1),
                frames=list(self.rec_frames),lifecycle=list(self.rec_lifecycle),validity=validity,provenance=self.provenance())

    def persist(self):
        """Keep the recording past session expiry. A storage failure is logged, never hidden by a fake success."""
        with self.lock:
            if not self.rich or not self.rec_dirty: return
            try:
                RECORDINGS[self.session_id]=self.recording()
                self.rec_dirty=False
            except Exception:  # noqa: BLE001 - persistence must not break the live session
                log.exception("could not persist recording for %s",self.session_id)

    def pending_messages(self, last_lifecycle, last_frame):
        """Lifecycle messages and the latest frame newer than the given sequences, in sequence order."""
        with self.lock:
            out=[m for m in self.lifecycle if m.sequence>last_lifecycle]
            frame=self.latest
            if frame is not None and (frame.sequence is None or frame.sequence>last_frame): out.append(frame)
            if self.rich: out.sort(key=lambda m: m.sequence)
            return out

    # ---- control ----

    def reanchor(self):
        self.anchor_wall=self.clock(); self.anchor_sim=self.model.t; self.lag_s=0.0

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
                self.persist()

    def tick(self):
        with self.lock:
            if self.connection is None or self.paused or self.error: return
            dt=self.model.dt
            elapsed=max(0,self.clock()-self.anchor_wall)
            wanted=min(self.model.duration,self.anchor_sim+math.floor((elapsed*self.speed+1e-9)/dt)*dt)
            # Bounded work per iteration (contact may subdivide). Incoming messages never call this.
            target=min(wanted,self.model.t+max(10,math.ceil(10*self.speed))*dt)
            self.lag_s=max(0.0,wanted-target)/self.speed  # wall seconds the scheduler is behind; never skipped
            if target > self.model.t+1e-9:
                alerts=[f"Simulation lagging wall clock by {self.lag_s:.1f} s at {self.speed:g}x"] if self.lag_s>LAG_ALERT_S else None
                try:
                    self.model.advance(target)
                    self.publish(alerts)
                    if self.model.t>=self.model.duration-1e-9 and self.state!="ended":
                        if self.rich and not self.rec_full and self.rec_frames[-1] is not self.latest: self.record_frame(self.latest)
                        self.emit("ended"); self.persist()
                except (ValueError,OverflowError) as exc:
                    self.model.invalid=True
                    self.model.reasons.append(ValidityReason(code="DYNAMICS_INTEGRATION_FAILED",message=str(exc)))
                    self.error="Integration stopped; reset or create a new session."
                    self.publish([self.error])
                    self.emit("error",f"{self.error} ({exc})"); self.persist()
                self.changed.set()

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
                    self.model=berthing_sim.BerthingModel(*self.initial,dt=self.model.dt,duration=self.model.duration)
                    self.paused=True; self.error=None
                    self.reanchor()
                    if self.rich:
                        self.run_id=new_id("run"); self.next_record_t=0.0
                        self.emit("reset")
                    self.publish(); self.persist()
                    self.changed.set()
                    return
                elif msg.type=="pause": self.paused=True
                elif not self.error: self.paused=False
                self.reanchor()
                if msg.type=="pause" and self.state in ("created","running"): self.emit("paused")
                elif msg.type=="resume" and not self.error and self.state in ("created","paused","reset"): self.emit("running")
                self.publish()
                if msg.type=="pause": self.persist()
                self.changed.set()
            elif msg.type=="set_speed":
                self.speed=float(msg.speed)
                self.reanchor()
                self.emit(self.state,self.error if self.state=="error" else None)
                self.changed.set()
            else:
                # Omitted timestamp targets the next boundary. Explicit times are
                # ordered by timestamp then arrival sequence, never retroactive.
                if msg.t_s is None:
                    msg=msg.model_copy(update={"t_s":min(self.model.duration,self.model.t+self.model.dt)})
                self.model.schedule(msg)

    async def run(self):
        try:
            while self.connection is not None:
                self.tick()
                await asyncio.sleep(min(0.05,self.model.dt))
        except asyncio.CancelledError:
            raise


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
