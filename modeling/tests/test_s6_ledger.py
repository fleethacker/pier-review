"""S6 review-ledger regression: finding 9 (future manual tug command must not suppress earlier auto-assist)."""

from s6_helpers import run, states, vessel


def _auto_vessel(tug_commands):
    route = [{"lat": 37.0, "lon": -76.02, "speed_kt": 3.0}]  # due west; ship heads north, so auto-assist must turn it
    return vessel(speed=0.0, heading=0.0, route=route, mode="tug_assisted",
                  tug_assist={"policy": "auto", "tug_ids": ["T1", "T2"], "assist_below_kt": 5.0},
                  helm=[{"t_s": 0, "engine_order": 0.0}], tug_commands=tug_commands)


def test_future_manual_command_does_not_suppress_earlier_auto_assist():
    late = [{"t_s": 150.0, "tug_id": "T1", "point": "port_shoulder", "force_lbf": 1000, "direction_rel_deg": 90.0}]
    r = run([_auto_vessel(late)], dur=200, dt=0.2, sample=2.0)
    fr = [(f.t_s, next(v for v in f.vessels if v.vessel_id == "A")) for f in r.frames]
    early = [(t, s) for t, s in fr if 10.0 <= t < 140.0]
    t1_sources = {tug.source for _, s in early for tug in s.tugs if tug.tug_id == "T1"}
    assert t1_sources == {"auto_assist"}, "T1 must be auto-assisting before its first manual command"
    assert any(tug.force_lbf > 1000 for _, s in early for tug in s.tugs if tug.tug_id == "T1")
    after = [tug.source for t, s in fr if t >= 160.0 for tug in s.tugs if tug.tug_id == "T1"]
    assert after and set(after) == {"command"}, "from its first manual command T1 belongs to the operator"
    # T2 (never commanded) keeps auto-assisting throughout
    assert {tug.source for _, s in fr for tug in s.tugs if tug.tug_id == "T2"} == {"auto_assist"}


def test_manual_command_at_t0_still_owns_the_tug():
    now = [{"t_s": 0.0, "tug_id": "T1", "point": "port_shoulder", "force_lbf": 1000, "direction_rel_deg": 90.0}]
    st = states(run([_auto_vessel(now)], dur=60, dt=0.2, sample=2.0))
    assert {t.source for s in st for t in s.tugs if t.tug_id == "T1"} == {"command"}
