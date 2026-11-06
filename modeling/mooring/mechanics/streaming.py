"""Incremental RK4 integration using dynamics.rk4, with independent dense sampling.

This extends the analytic integrator without changing its public behavior. Event
locations are numerical crossings, not a validated impact or rope rupture law.
"""
import math
from .dynamics import rk4


class Integrator:
    def __init__(self, params, forces, state, dt, *, events=None, gap=None, coupled_step=None, auxiliary_state=(), step_speed=None):
        if not math.isfinite(dt) or dt < 1e-4:
            raise ValueError("integration step must be finite and at least 0.0001 s")
        self.params, self.forces, self.state, self.dt = params, forces, state, dt
        self.events, self.gap = events or {}, gap
        self.t, self.steps = 0.0, 0
        self.crossings = []
        self.previous = (0.0, state)
        self.coupled_step = coupled_step
        self.auxiliary_state = tuple(auxiliary_state)
        self.previous_auxiliary_state = tuple(auxiliary_state)
        self.step_speed = step_speed

    def step(self, t, state, auxiliary, dt):
        if self.coupled_step is not None:
            return self.coupled_step(t,state,auxiliary,dt)
        return rk4(self.params,self.forces,t,state,dt),auxiliary

    def advance(self, end, *, check=lambda: None, observe=lambda *args: None):
        while self.t < end - 1e-10:
            check()
            t, s = self.t, self.state
            auxiliary = self.auxiliary_state
            h = min(self.dt, end - t)
            if self.gap:
                distance = abs(self.gap(s))
                speed = max(self.step_speed(s) if self.step_speed else math.hypot(s[3], s[4]), 1e-8)
                if distance < 5 * speed * h:
                    h = min(h, max(1e-4, 0.25 * distance / speed))
            nxt, next_auxiliary = self.step(t,s,auxiliary,h)
            if not all(math.isfinite(v) for v in (*nxt,*next_auxiliary)):
                raise ValueError("non-finite integrated state")
            for name, fn in sorted(self.events.items()):
                old, new = fn(t, s), fn(t+h, nxt)
                if (old > 0) != (new > 0):
                    lo, hi = 0.0, h
                    for _ in range(40):
                        mid = (lo+hi)/2
                        if (fn(t+mid, self.step(t,s,auxiliary,mid)[0]) > 0) == (old > 0):
                            lo = mid
                        else:
                            hi = mid
                        if hi-lo < 1e-8:
                            break
                    self.crossings.append((t+hi, name, new > 0))
            self.previous = (t, s)
            self.previous_auxiliary_state = auxiliary
            self.auxiliary_state = next_auxiliary
            self.t, self.state = t+h, nxt
            self.steps += 1
            observe(t, s, self.t, nxt)

    def sample(self, t):
        start, state = self.previous
        if not start-1e-9 <= t <= self.t+1e-9:
            raise ValueError("sample must lie in the most recent integration step")
        return self.step(start,state,self.previous_auxiliary_state,max(0,t-start))[0]

    def sample_auxiliary(self, t):
        start,state = self.previous
        if not start-1e-9 <= t <= self.t+1e-9:
            raise ValueError("sample must lie in the most recent integration step")
        if abs(t-self.t) < 1e-10:
            return self.auxiliary_state
        return self.step(start,state,self.previous_auxiliary_state,max(0,t-start))[1]
