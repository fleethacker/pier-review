"""Single-owner interactive sessions. Only the scheduler advances physics.

Disconnected/paused sessions freeze. Reconnect resumes from the same state only
on an explicit resume command; there is no wall-clock catch-up across disconnect.
Output is a latest-frame slot, so a slow socket cannot queue unbounded history.
"""
import asyncio
import math
import os
import threading
import time

from mooring.core import access
from .backend import berthing_sim


class Session:
    def __init__(self, model, *, clock=time.monotonic):
        self.model,self.clock=model,clock
        self.initial=(model.sc.model_copy(deep=True),model.initial.model_copy(deep=True),model.env.model_copy(deep=True))
        self.lock=threading.RLock()
        self.connection=None
        self.paused=False
        self.anchor_wall=clock()
        self.anchor_sim=0.0
        self.changed=asyncio.Event()
        self.latest=model.frame()
        self.last_access=clock()
        self.received=0
        self.window_start=clock()
        self.error=None

    def attach(self, connection):
        with self.lock:
            if self.connection is not None: raise ValueError("session already has an active controller")
            self.connection=connection
            self.changed=asyncio.Event()
            self.anchor_wall=self.clock(); self.anchor_sim=self.model.t
            self.last_access=self.clock()

    def detach(self, connection):
        with self.lock:
            if self.connection==connection:
                self.connection=None
                self.paused=True
                self.anchor_sim=self.model.t; self.anchor_wall=self.clock()
                self.last_access=self.clock()

    def tick(self):
        with self.lock:
            if self.connection is None or self.paused or self.error: return
            elapsed=max(0,self.clock()-self.anchor_wall)
            target=min(self.model.duration,self.anchor_sim+math.floor((elapsed+1e-9)/self.model.dt)*self.model.dt)
            # At most ten nominal time increments per iteration (contact may subdivide).
            # Incoming messages never call this.
            target=min(target,self.model.t+10*self.model.dt)
            if target > self.model.t+1e-9:
                try:
                    self.model.advance(target)
                    self.latest=self.model.frame()
                except (ValueError,OverflowError) as exc:
                    from mooring.core.schemas import ValidityReason
                    self.model.invalid=True
                    self.model.reasons.append(ValidityReason(code="DYNAMICS_INTEGRATION_FAILED",message=str(exc)))
                    self.error="Integration stopped; reset or create a new session."
                    self.latest=self.model.frame(alerts=[self.error])
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
                elif msg.type=="pause": self.paused=True
                elif not self.error: self.paused=False
                self.anchor_wall=now; self.anchor_sim=self.model.t
                self.latest=self.model.frame()
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

def create(sessions, sid, model):
    with _CREATE_LOCK:
        return _create(sessions, sid, model)

def _create(sessions, sid, model):
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
    sessions[sid]=Session(model)
    return sessions[sid]
