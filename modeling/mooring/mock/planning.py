"""Mock configuration optimizer and line sequence (M7).

Recommend: a fixed six-line template per ship snapped to the nearest free pier bollards on the pier edge (never the
set-back row), offered in three variants and scored with the mock solver. Forward: a head line and two crossing
lines. Aft: two crossing lines and a stern (storm) line that leads straight astern behind them.
Sequence: a rule table based on NSTM 582-2.4.6. Workstream D replaces both with search and an SME-reviewed table.
"""

import math

from mooring import refdata
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    Berth,
    Candidate,
    EnvironmentSnapshot,
    MooringConfig,
    MooringLine,
    RecommendRequest,
    RecommendResponse,
    RecommendResult,
    SequenceRequest,
    SequenceResponse,
    SequenceResult,
    SequenceStep,
    ShipClass,
)
from mooring.rules.nstm582 import MST_LIMITS

from ._common import envelope
from .mooring import solve

# (line number, role). Line n leaves from the ship's bitt n: 1 bow, 2-3 forward crossing pair, 4-5 aft crossing pair,
# 6 stern (the storm line). In a crossing pair the more-forward bitt leads aft and the more-aft bitt leads forward.
TEMPLATE = [
    (1, "bow"),
    (2, "spring_aft"),
    (3, "spring_fwd"),
    (4, "spring_aft"),
    (5, "spring_fwd"),
    (6, "stern"),
]
END_LINES_DOUBLED = {1: 3, 6: 3}  # the head and storm lines take the most load when the springs cross
END_LEAD_FT = 60.0  # head and storm lines reach this far past their chock along the ship
CROSS_MARGIN_FT = 15.0  # a crossing pair's bollards sit at least this far either side of the pair's midpoint
NEAR_ROW_Y_FT = -20.0  # pier fittings set back farther than this are not used


def design_environment(berth: Berth, side_to: str, mst: str, water_level_ft: float = 0.0) -> EnvironmentSnapshot:
    """MST design condition with wind and current both pushing the ship off the pier (NSTM Table 582-1-1)."""
    wind_kt, current_kt = max(MST_LIMITS[mst])
    heading = ship_heading_true(berth, side_to)
    pier_side = (heading + (90 if side_to == "starboard" else 270)) % 360  # bearing from ship to pier
    return EnvironmentSnapshot(source="scenario", wind_speed_kt=wind_kt, wind_gust_kt=wind_kt,
                               wind_from_true_deg=pier_side, current_speed_kt=current_kt,
                               current_set_true_deg=(pier_side + 180) % 360, water_level_mllw_ft=water_level_ft)


def template_config(ship: ShipClass, berth: Berth, side_to: str, ship_x_ft: float, spec_id: str,
                    parts: dict[int, int] | None = None, excluded: set[str] | None = None) -> MooringConfig:
    s = "S" if side_to == "starboard" else "P"
    fittings = {f.fitting_id: f for f in ship.fittings}
    if not fittings:
        raise refdata.InvalidReference(f"{ship.class_id} has no fittings in the seed data yet; use DDG-51-FIIA.")
    bow_dir = 1 if side_to == "starboard" else -1
    usable = [f for f in berth.fittings if f.condition == "good" and not f.occupied_by
              and f.kind.startswith("bollard") and f.fitting_id not in (excluded or set())]
    near = [f for f in usable if f.y_ft >= NEAR_ROW_Y_FT] or usable
    if not near:
        raise refdata.InvalidReference(f"{berth.berth_id} has no usable bollards.")

    def u(f) -> float:  # pier fitting position along the ship, + forward of midships
        return bow_dir * (f.x_ft - ship_x_ft)

    bitt = {n: fittings[f"BITT-{n}{s}"] for n, _ in TEMPLATE}
    lead_x = {n: fittings.get(b.paired_chock_id or "", b).x_ft for n, b in bitt.items()}
    by_id = {f.fitting_id: f for f in berth.fittings}
    used: set[str] = set()
    pier: dict[int, str] = {}

    def free(pool):
        return [f for f in pool if f.fitting_id not in used]

    def cross(fwd_n: int, aft_n: int) -> None:
        """The bollards either side of the pair's midpoint; the forward bitt takes the aft one, so the lines cross."""
        mid = (lead_x[fwd_n] + lead_x[aft_n]) / 2
        pool = free(near) or free(usable)
        behind = [f for f in pool if u(f) < mid - CROSS_MARGIN_FT]
        ahead = [f for f in pool if u(f) > mid + CROSS_MARGIN_FT]
        if behind and ahead:
            lo, hi = max(behind, key=u), min(ahead, key=u)
        else:  # near the end of the face: the two nearest will do
            lo, hi = sorted(sorted(pool, key=lambda f: abs(u(f) - mid))[:2], key=u)
        pier[fwd_n], pier[aft_n] = lo.fitting_id, hi.fitting_id
        used.update((lo.fitting_id, hi.fitting_id))

    def end(n: int, forward: bool, pair: tuple[int, int]) -> None:
        """Head or storm line: the bollard nearest its target that lies beyond its group's crossing lines."""
        pts = [u(by_id[pier[k]]) for k in pair]
        pool = free(near) or free(usable)
        beyond = [f for f in pool if (u(f) > max(pts) if forward else u(f) < min(pts))]
        target = lead_x[n] + (END_LEAD_FT if forward else -END_LEAD_FT)
        choice = min(beyond or pool, key=lambda f: abs(u(f) - target))
        pier[n] = choice.fitting_id
        used.add(choice.fitting_id)

    cross(2, 3)
    cross(4, 5)
    end(1, forward=True, pair=(2, 3))
    end(6, forward=False, pair=(4, 5))

    lines = [MooringLine(line_number=n, role=role, spec_id=spec_id, parts=(parts or {}).get(n, 1),
                         ship_fitting_id=bitt[n].fitting_id, pier_fitting_id=pier[n]) for n, role in TEMPLATE]
    return MooringConfig(side_to=side_to, ship_x_ft=ship_x_ft, lines=lines)


def recommend(req: RecommendRequest) -> RecommendResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    ship_x = req.ship_x_ft if req.ship_x_ft is not None else berth.face_length_ft / 2
    outfit = req.available_lines or ship.standard_line_outfit
    nylon = next((i.spec_id for i in outfit if "NYLON" in i.spec_id), outfit[0].spec_id if outfit else "NYLON-DB-7IN")
    aramid = next((i.spec_id for i in outfit if "ARAMID" in i.spec_id), None)
    design_env = design_environment(berth, req.side_to, req.design_mst)
    excluded = set(req.excluded_fitting_ids)
    variants = [("single part " + nylon, nylon, None),
                ("head and storm lines doubled up (3 parts) " + nylon, nylon, END_LINES_DOUBLED),
                ("all lines doubled up (3 parts) " + nylon, nylon, {n: 3 for n in range(1, 7)})]
    if aramid:
        variants.insert(1, ("single part " + aramid, aramid, None))
    candidates = []
    for label, spec, parts in variants[: req.max_candidates]:
        cfg = template_config(ship, berth, req.side_to, ship_x, spec, parts, excluded)
        if req.locked_lines:
            locked = {ln.line_number: ln for ln in req.locked_lines}
            cfg.lines = [locked.get(ln.line_number, ln) for ln in cfg.lines]
        cfg.config_id = f"cfg-{len(candidates) + 1}"
        areq = AnalyzeRequest(ship_class_id=ship.class_id, loading=req.loading, berth_id=berth.berth_id,
                              config=cfg, environment=design_env, mst=req.design_mst)
        s = solve(areq)
        env = envelope(AnalyzeResponse, model="mooring.solver.static", request=areq, result=s.result,
                       status=s.status)
        top = s.result.min_margin
        limit = (design_env.wind_speed_kt * math.sqrt(100 / top.pct_wll)) if top.pct_wll > 0 else None
        candidates.append(Candidate(
            config=cfg, min_margin_pct_wll=top.pct_wll, limit_wind_kt_worst=round(limit, 1) if limit else None,
            line_count=len(cfg.lines), analysis_result_id=env.result_id,
            why=[f"Template: {label}.", f"Highest utilization {top.pct_wll:.0f}% ({top.element_id}) at MST "
                 f"{req.design_mst} design wind {design_env.wind_speed_kt:.0f} kt off the pier."]))
    candidates.sort(key=lambda c: c.min_margin_pct_wll)
    best = candidates[0].min_margin_pct_wll if candidates else 999
    status = "GREEN" if best <= 80 else "AMBER" if best <= 100 else "RED"
    return envelope(RecommendResponse, model="mooring.planning.optimizer", request=req,
                    result=RecommendResult(candidates=candidates, design_environment=design_env), status=status,
                    assumptions=["Mock optimizer: fixed six-line template snapped to the nearest good bollards."])


def _station(ship: ShipClass, x_ft: float) -> str:
    if x_ft > 0.25 * ship.loa_ft:
        return "forecastle"
    if x_ft < -0.25 * ship.loa_ft:
        return "fantail"
    return "waist"


def sequence(req: SequenceRequest) -> SequenceResponse:
    ship = refdata.ship(req.ship_class_id)
    fittings = {f.fitting_id: f for f in ship.fittings}
    lines = {ln.line_number: ln for ln in req.config.lines}

    def station(n: int) -> str:
        f = fittings.get(lines[n].ship_fitting_id)
        return _station(ship, f.x_ft) if f else "waist"

    order = [n for n in (2, 5, 3, 4, 1, 6) if n in lines] + sorted(n for n in lines if n not in (1, 2, 3, 4, 5, 6))
    tugs_holding = req.tug_plan_result_id is not None
    steps: list[SequenceStep] = []

    def add(line: int | None, action: str, st: str, trigger: str, caution: str | None = None,
            ref: str = "NSTM 582-2.4.6") -> None:
        steps.append(SequenceStep(step=len(steps) + 1, line_number=line, action=action, station=st, crews=1,
                                  trigger=trigger, caution=caution, reference=ref))

    for i, n in enumerate(order):
        trig = "Bridge orders first line over" if i == 0 else f"Line {order[i - 1]} on its bollard"
        add(n, "pass", station(n), trig)
        add(n, "secure_pier", "pier", f"Line {n} eye ashore",
            ref="NSTM 582-2.4.6.3")
        if tugs_holding and lines[n].role in ("breast", None):
            add(n, "hold", station(n), "Tugs holding the ship alongside",
                caution="Keep this line slack-tended; don't take it to power until the tugs ease off.",
                ref="NSTM 582-2.2.3.1")
    add(None, "hold", "bridge", "All lines on their bollards; tugs ease off" if tugs_holding else "All lines on their bollards")
    for n in order:
        add(n, "take_to_power", station(n), "Bridge orders lines taken to power", ref="NSTM 582-2.4.6.5")
        if lines[n].parts > 1:
            add(n, "double_up", station(n), f"Line {n} tensioned", ref="NSTM 582-2.4.6.4")
    add(None, "tend", "bridge", "All lines doubled up and tensioned",
        caution="Equalize: slack the shortest lines about 1 ft; pre-tension lines over 100 ft.",
        ref="NSTM 582-2.4.4.1.c")
    crews = max(4, min(len(lines), 8))
    if req.line_handling_crews < 4:
        steps[0].caution = f"Only {req.line_handling_crews} crews available; at least 4 are needed (NSTM 582-2.4.6.1)."
    status = "AMBER" if req.line_handling_crews < crews else "GREEN"
    return envelope(SequenceResponse, model="mooring.planning.sequence", request=req,
                    result=SequenceResult(steps=steps, crews_required=crews), status=status,
                    assumptions=["Mock sequence rule table; to be reviewed by a deck officer or pilot."])
