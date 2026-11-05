"""S7b: the S6 transit integrator driven by an S2 ForcingSeries.

The transit simulator holds one fixed environment per run. This module does NOT add a second forcing resolver or dynamics:
it evaluates the SAME `mooring.berthing.forcing.ForcingSeries.at(t)` at prediction-relative simulation time (t = 0 is the
snapshot / as_of time) and hands the result to the unchanged `transit.simulator.Vessel`. The series is sampled once at the
start of each integration step (zero-order hold over dt <= 1 s), not at RK4 stage times: a documented approximation.
"""
import math
from datetime import timedelta

from mooring.core.forcing import ForcingSeries, ForcingUncovered
from mooring.core.schemas import TrackFix, TransitFrame
from mooring.transit import simulator as sim

KT = sim.KT


def _apply(v, env):
    v.env = env
    vc = env.current_speed_kt * KT
    th = math.radians(env.current_set_true_deg)
    v.cur = (vc * math.sin(th), vc * math.cos(th))


def run(req, series: ForcingSeries, xform=None, job_id: str = "predict") -> sim.Run:
    """Mirror of transit.simulator.run with the environment re-sampled from `series` each step.
    `xform(env) -> env` perturbs the sampled environment (uncertainty samples). Raises sim.RequestInvalid if uncovered."""
    plane, _env, _rho, vessels = sim.prepare(req)
    sample = req.sample_interval_s or sim.DEFAULT_SAMPLE_S
    dt, every = sim.effective_step(req.dt_s, sample)
    n_frames = int(math.floor(req.duration_s / sample + 1e-9))
    start = req.start_utc or sim.EPOCH
    frames = []

    def set_env(t):
        try:
            env, _covered = series.at(t)
        except ForcingUncovered as exc:
            raise sim.RequestInvalid(f"FORCING_UNCOVERED: {exc}") from None
        env = xform(env) if xform else env
        for v in vessels:
            _apply(v, env)

    def emit(k):
        t = k * sample
        set_env(t)
        for v in vessels:
            v.wind = v.wind_wrench(v.s)
            st = v.state_model(t)
            v.track.append(TrackFix(t_utc=start + timedelta(seconds=t), lat=st.lat, lon=st.lon, heading_true_deg=st.heading_true_deg,
                                    cog_true_deg=st.cog_true_deg, sog_kt=st.sog_kt, quality="unknown", source=f"simulated:{job_id}"))
            v._cur = st
        frames.append(TransitFrame(t_s=t, t_utc=start + timedelta(seconds=t) if req.start_utc else None,
                                   vessels=[v._cur for v in vessels]))

    emit(0)
    last = 0
    for step in range(1, n_frames * every + 1):
        set_env((step - 1) * dt)
        for v in vessels:
            v.step(dt)
        last = step
        if step % every == 0:
            emit(step // every)
            if all(v.invalid or v.status != "underway" for v in vessels):
                break
    r = sim.Run(frames, sorted((e for v in vessels for e in v.events), key=lambda e: (e.t_s, e.vessel_id)), vessels, plane, start,
                req.start_utc is None, sample, last * dt)
    r.dt_s = dt
    return r
