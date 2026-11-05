"""Incremental RK4 integration using dynamics.rk4, with independent dense sampling.

This extends the analytic integrator without changing its public behavior. Event
locations are numerical crossings, not a validated impact or rope rupture law.
"""
import math
from .dynamics import rk4


class Integrator:
    def __init__(self, params, forces, state, dt, *, events=None, gap=None):
        if not math.isfinite(dt) or dt < 1e-4:
            raise ValueError("integration step must be finite and at least 0.0001 s")
        self.params, self.forces, self.state, self.dt = params, forces, state, dt
        self.events, self.gap = events or {}, gap
        self.t, self.steps = 0.0, 0
        self.crossings = []
        self.previous = (0.0, state)

    def advance(self, end, *, check=lambda: None, observe=lambda *args: None):
        while self.t < end - 1e-10:
            check()
            t, s = self.t, self.state
            h = min(self.dt, end - t)
            if self.gap:
                distance = abs(self.gap(s))
                speed = max(math.hypot(s[3], s[4]), 1e-8)
                if distance < 5 * speed * h:
                    h = min(h, max(1e-4, 0.25 * distance / speed))
            nxt = rk4(self.params, self.forces, t, s, h)
            if not all(math.isfinite(v) for v in nxt):
                raise ValueError("non-finite integrated state")
            for name, fn in sorted(self.events.items()):
                old, new = fn(t, s), fn(t+h, nxt)
                if (old > 0) != (new > 0):
                    lo, hi = 0.0, h
                    for _ in range(40):
                        mid = (lo+hi)/2
                        if (fn(t+mid, rk4(self.params, self.forces, t, s, mid)) > 0) == (old > 0):
                            lo = mid
                        else:
                            hi = mid
                        if hi-lo < 1e-8:
                            break
                    self.crossings.append((t+hi, name, new > 0))
            self.previous = (t, s)
            self.t, self.state = t+h, nxt
            self.steps += 1
            observe(t, s, self.t, nxt)

    def sample(self, t):
        start, state = self.previous
        if not start-1e-9 <= t <= self.t+1e-9:
            raise ValueError("sample must lie in the most recent integration step")
        return rk4(self.params, self.forces, start, state, max(0, t-start))
