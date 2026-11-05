"""S15/S16: the synthetic-parameter integrator against independent analytic solutions.

These validate the integrator and contact logic only. No real vessel coefficients are held in this repository."""

import math

import pytest

from mooring.fixtures import breast_config, calm_env, synthetic_berth, synthetic_line_spec, synthetic_ship, tug
from mooring.mechanics import Pose, equilibrium as eq
from mooring.mechanics import dynamics as dyn
from mooring.mechanics.dynamics import BodyParams, MooredBody, kinetic_energy, simulate

P = BodyParams(mass_slug=1.0e5, izz_slug_ft2=4.0e9, added_surge=2.0e4, added_sway=5.0e4, added_yaw=1.0e9)
M11, M22, M33 = P.m
ZERO = lambda t, s: (0.0, 0.0, 0.0)


def test_zero_input_stays_at_rest_and_invalid_parameters_are_rejected():
    tr = simulate(P, ZERO, (10.0, 20.0, 0.3, 0.0, 0.0, 0.0), 5.0, 0.1)
    assert all(s == (10.0, 20.0, 0.3, 0.0, 0.0, 0.0) for s in tr.states)
    for kw in (dict(mass_slug=0.0, izz_slug_ft2=1.0), dict(mass_slug=1.0, izz_slug_ft2=-1.0), dict(mass_slug=1, izz_slug_ft2=1, damping_lin=(-1, 0, 0)),
               dict(mass_slug=1, izz_slug_ft2=1, added_sway=-1)):
        with pytest.raises(ValueError):
            BodyParams(**kw)


def test_constant_force_gives_constant_acceleration():
    F = 5_000.0
    tr = simulate(P, lambda t, s: (F, 0.0, 0.0), (0, 0, 0, 0, 0, 0), 10.0, 0.05)
    x, _, _, u, _, _ = tr.states[-1]
    assert x == pytest.approx(F * 10.0**2 / (2 * M11), rel=1e-9) and u == pytest.approx(F * 10.0 / M11, rel=1e-9)


def test_free_decay_with_linear_damping_is_exponential():
    d = 3_000.0
    p = BodyParams(1.0e5, 4.0e9, 2.0e4, 5.0e4, 1.0e9, damping_lin=(d, 0, 0))
    tr = simulate(p, ZERO, (0, 0, 0, 2.0, 0, 0), 60.0, 0.05)
    for t, s in zip(tr.t, tr.states):
        assert s[3] == pytest.approx(2.0 * math.exp(-d * t / p.m[0]), rel=1e-7, abs=1e-12)


def test_pure_yaw_moment():
    N = 2.0e6
    tr = simulate(P, lambda t, s: (0.0, 0.0, N), (0, 0, 0, 0, 0, 0), 20.0, 0.05)
    _, _, psi, _, _, r = tr.states[-1]
    assert r == pytest.approx(N * 20.0 / M33, rel=1e-9) and psi == pytest.approx(N * 20.0**2 / (2 * M33), rel=1e-9)
    assert abs(tr.states[-1][3]) < 1e-9 and abs(tr.states[-1][4]) < 1e-9   # no coupling into translation from a pure moment at rest


def test_body_frame_force_rotates_with_heading():
    tr = simulate(P, lambda t, s: (4_000.0, 0.0, 0.0), (0, 0, math.pi / 2, 0, 0, 0), 5.0, 0.05)
    x, y, *_ = tr.states[-1]
    assert abs(x) < 1e-9 and y == pytest.approx(4_000.0 * 25 / (2 * M11), rel=1e-9)   # heading 90 degrees: surge moves along +y


def test_mirror_symmetry_in_sway_and_yaw():
    f = lambda sgn: (lambda t, s: (1_000.0, sgn * 3_000.0, sgn * 1.0e6))
    a = simulate(P, f(+1), (0, 0, 0, 1.0, 0, 0), 8.0, 0.02).states[-1]
    b = simulate(P, f(-1), (0, 0, 0, 1.0, 0, 0), 8.0, 0.02).states[-1]
    assert (a[0], a[3]) == pytest.approx((b[0], b[3]), rel=1e-9) and (a[1], a[2], a[4], a[5]) == pytest.approx(tuple(-v for v in (b[1], b[2], b[4], b[5])), rel=1e-9)


def test_undamped_spring_conserves_energy_and_damped_system_never_gains_it():
    k = 3.0e5
    spring = lambda t, s: (0.0, -k * s[1], 0.0)
    e0 = 0.5 * k * 2.0**2
    tr = simulate(P, spring, (0, 2.0, 0, 0, 0, 0), 20.0, 0.01)
    es = [0.5 * k * s[1] ** 2 + kinetic_energy(P, s) for s in tr.states]
    assert max(abs(e - e0) for e in es) / e0 < 1e-6
    pd = BodyParams(1.0e5, 4.0e9, 2.0e4, 5.0e4, 1.0e9, damping_lin=(0, 4_000.0, 0), damping_quad=(0, 500.0, 0))
    trd = simulate(pd, spring, (0, 2.0, 0, 0, 0, 0), 20.0, 0.01)
    ed = [0.5 * k * s[1] ** 2 + kinetic_energy(pd, s) for s in trd.states]
    assert all(b <= a + 1e-6 * e0 for a, b in zip(ed, ed[1:]))


def test_timestep_refinement_shows_fourth_order_convergence():
    k = 3.0e5
    w = math.sqrt(k / M22)
    exact = lambda t: 2.0 * math.cos(w * t)
    err = []
    for dt in (0.2, 0.1, 0.05):
        tr = simulate(P, lambda t, s: (0.0, -k * s[1], 0.0), (0, 2.0, 0, 0, 0, 0), 6.0, dt)
        err.append(abs(tr.states[-1][1] - exact(6.0)))
    assert err[0] / err[1] > 10 and err[1] / err[2] > 10   # ~16 for RK4


def test_sampling_is_independent_of_the_integration_step():
    a = simulate(P, lambda t, s: (1000, 0, 0), (0, 0, 0, 0, 0, 0), 3.0, 0.01, sample_dt=0.5)
    b = simulate(P, lambda t, s: (1000, 0, 0), (0, 0, 0, 0, 0, 0), 3.0, 0.005, sample_dt=0.5)
    assert a.t == b.t and len(a.t) == 7 and a.states[-1][0] == pytest.approx(b.states[-1][0], rel=1e-9)


# ---------- contact, lines, events (S16) ----------

SHIP, BERTH, SPEC = synthetic_ship(), synthetic_berth(), synthetic_line_spec()
K_FENDER = 3 * 100_000.0     # three fenders, symmetric about midships: no yaw


def body(cfg=None, tugs=None, standoff=11.0, **kw):
    c = cfg or breast_config(standoff=standoff)
    if cfg is None:
        c.lines = []
    system = eq.build_system(SHIP, BERTH, c, {SPEC.spec_id: SPEC}, calm_env(), loading="full_load", lines_wet=False, tugs=tugs)
    return MooredBody(system, kw.get("params", P))


def test_spring_impact_matches_the_analytic_solution():
    b = body()                                      # 1 ft gap to the fenders
    v0 = 1.0
    s0 = b.state_at(Pose(), v=-v0)
    tr = simulate(P, b.forces, s0, 4.0, 0.005, sample_dt=0.01, events=b.events(), gap=b.contact_gap)
    w = math.sqrt(K_FENDER / M22)
    d_max = v0 / w
    peak = max(max(b.fender_deflections(s)) for s in tr.states)
    assert peak == pytest.approx(d_max, rel=2e-3)
    starts = [e for e in tr.events if e.name.startswith("contact:") and e.t < 1.5]
    assert starts and all(e.t == pytest.approx(1.0, abs=1e-6) for e in starts)           # gap / speed
    t_leave = 1.0 + math.pi / w
    assert tr.events[-1].t == pytest.approx(t_leave, abs=2e-3)                              # one half period in contact
    assert tr.states[-1][4] == pytest.approx(+v0, rel=1e-3)                                 # elastic: leaves at the same speed


def test_fender_force_is_never_tensile_and_energy_is_balanced():
    b = body()
    s0 = b.state_at(Pose(), v=-1.0)
    tr = simulate(P, b.forces, s0, 4.0, 0.005, sample_dt=0.02, events=b.events(), gap=b.contact_gap)
    e0 = b.energy(tr.states[0])
    for s in tr.states:
        assert b.system.total_wrench(b.pose(s)).fy_lbf >= -1e-9      # fenders only ever push the ship off the pier
        assert b.energy(s) == pytest.approx(e0, rel=2e-3)


def test_contact_time_converges_with_the_timestep():
    errs = []
    for dt in (0.05, 0.01, 0.002):
        b = body()
        tr = simulate(P, b.forces, b.state_at(Pose(), v=-1.0), 2.0, dt, sample_dt=0.1, events=b.events(), gap=b.contact_gap)
        errs.append(abs(next(e.t for e in tr.events if e.name.startswith("contact:")) - 1.0))
    assert max(errs) < 1e-6   # event time is located by bisection, not by the step size


def test_line_take_up_event_time_matches_geometry_and_energy_is_conserved():
    cfg = breast_config(pretension=None, pairs=(1, 4), standoff=14.0)       # ship 4 ft off the fenders; lines slack by 2 ft
    for ln in cfg.lines:
        ln.slack_ft = 2.0
    b = body(cfg=cfg)
    v0 = 0.8
    l_init = math.hypot(20.0, 10.5)
    delta = math.sqrt((l_init + 2.0) ** 2 - 10.5**2) - 20.0                  # sway at which the lines just become taut
    tr = simulate(P, b.forces, b.state_at(Pose(), v=+v0), 6.0, 0.005, sample_dt=0.02, events=b.events(), gap=b.contact_gap)
    taut = [e for e in tr.events if e.name.startswith("taut:")]
    assert taut and taut[0].t == pytest.approx(delta / v0, abs=1e-6)
    e0 = b.energy(tr.states[0])
    assert all(b.energy(s) == pytest.approx(e0, rel=5e-3) for s in tr.states)
    assert max(s[1] for s in tr.states) > b.frame.ref_y_ft + delta            # stretched the lines, then came back


def test_event_order_is_reproducible():
    def run():
        b = body()
        tr = simulate(P, b.forces, b.state_at(Pose(), v=-1.0, u=0.2), 4.0, 0.01, sample_dt=0.05, events=b.events(), gap=b.contact_gap)
        return [(round(e.t, 9), e.name) for e in tr.events], tr.states[-1]
    assert run() == run()


def test_slow_settling_agrees_with_the_static_equilibrium_solver():
    """Consistency (not validation): a damped moored ship under a constant tug force settles at the M4 equilibrium pose."""
    cfg = breast_config(pairs=(1, 2, 3, 4), springs=True, pretension=2_000.0)
    tugs = [tug("PP-FWD-P", 20_000.0, "pull", 0.0), tug("PP-AFT-P", 12_000.0, "pull", 0.0)]
    system = eq.build_system(SHIP, BERTH, cfg, {SPEC.spec_id: SPEC}, calm_env(), loading="full_load", lines_wet=False, tugs=tugs)
    ref = eq.solve(system)
    assert ref.converged
    params = BodyParams(1.0e5, 4.0e9, 2.0e4, 5.0e4, 1.0e9, damping_lin=(4.0e5, 4.0e5, 2.0e10))
    b = MooredBody(system, params)
    tr = simulate(params, b.forces, b.state_at(Pose()), 900.0, 0.05, sample_dt=100.0)
    pose = b.pose(tr.states[-1])
    assert (pose.dx_ft, pose.dy_ft, pose.dyaw_rad) == pytest.approx((ref.pose.dx_ft, ref.pose.dy_ft, ref.pose.dyaw_rad), abs=2e-3)
