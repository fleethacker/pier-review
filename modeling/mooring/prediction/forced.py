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
    start = req.start_utc or sim.EPOCH
    frames = []
    environment_issues = []
    environment_spread = False

    def set_env(t):
        try:
            env, _covered = series.at(t)
        except ForcingUncovered as exc:
            raise sim.RequestInvalid(f"FORCING_UNCOVERED: {exc}") from None
        env = xform(env) if xform else env
        for v in vessels:
            _apply(v, env)
        return env

    def emit(t):
        environment_issues.extend(sim.environment_evidence(set_env(t)))
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
    for _, t, step_dt, report in sim.integration_schedule(req.duration_s, dt, every):
        env = set_env(t - step_dt)
        environment_spread |= env.wind_speed_kt > 0 or env.current_speed_kt > 0
        for v in vessels:
            v.step(step_dt)
        last = t
        if report:
            emit(t)
            if all(v.invalid or v.status != "underway" for v in vessels):
                break
    r = sim.Run(frames, sorted((e for v in vessels for e in v.events), key=lambda e: (e.t_s, e.vessel_id)), vessels, plane, start,
                req.start_utc is None, sample, last, environment_issues=environment_issues,
                environment_spread=environment_spread)
    r.dt_s = dt
    return r
