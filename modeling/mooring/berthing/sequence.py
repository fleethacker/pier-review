"""Line-handling sequence (M7, berthing phase, S13): generation, dependency/resource validation and intermediate states.

A sequence is a set of steps with dependencies, crews and (optionally) tugs. It is validated structurally (unknown or
cyclic dependencies, out-of-order or duplicated per-line actions, unknown lines, missing line actions), against
resources (crews; referenced tug plan existence, type and scenario provenance), against line availability and lead, and
*per intermediate state*: after each line is secured or taken to power the equilibrium is solved with only the lines
then fast (and the referenced tugs while they hold). A valid final equilibrium alone does not validate a sequence.

Limits stated in every result: this is a static check. Transient loads while lines are handled and tugs maneuver are not
evaluated (they need the M11 simulator). The rule table is a draft from NSTM 582-2.4.6 paragraph references that have not
been re-verified in this repo; durations are unreviewed planning estimates. Output is `draft_unreviewed` until a deck
officer or pilot reviews it.
"""

import dataclasses

from mooring import refdata
from mooring.core.envelopes import RESULTS, envelope, status_with_validity
from mooring.core.geometry import line_geometry
from mooring.core.schemas import (
    MooringLine, SequenceIssue, SequenceRequest, SequenceResponse, SequenceResult, SequenceStep, SequenceValidateRequest, ShipClass,
    TugAssignment, Validity, ValidityReason,
)
from mooring.mechanics import equilibrium as eq
from mooring.rules.nstm582 import design_factor

DURATIONS = {"pass": 5.0, "secure_pier": 3.0, "hold": 0.0, "take_to_power": 4.0, "double_up": 6.0, "tend": 10.0}
MIN_CREWS = 4   # NSTM 582-2.4.6.1 as cited by the earlier rule table; not re-verified here
LIMITATIONS = [
    "Static check only: transient loads while lines are handled and tugs maneuver are not evaluated; they need the M11 simulator.",
    "Rule table is a draft from NSTM 582-2.4.6 paragraph references that were not re-verified in this repository.",
    "Durations are unreviewed planning estimates, not measured line-handling times.",
]
RULE_REF = {"pass": "NSTM 582-2.4.6", "secure_pier": "NSTM 582-2.4.6.3", "hold": "NSTM 582-2.2.3.1", "take_to_power": "NSTM 582-2.4.6.5",
            "double_up": "NSTM 582-2.4.6.4", "tend": "NSTM 582-2.4.4.1.c"}


def _station(ship: ShipClass, x_ft: float) -> str:
    return "forecastle" if x_ft > 0.25 * ship.loa_ft else "fantail" if x_ft < -0.25 * ship.loa_ft else "waist"


def generate_steps(ship: ShipClass, lines: dict[int, MooringLine], tugs_holding: bool, tug_ids: list[str]) -> list[SequenceStep]:
    fittings = {f.fitting_id: f for f in ship.fittings}
    steps: list[SequenceStep] = []

    def st(n: int) -> str:
        f = fittings.get(lines[n].ship_fitting_id)
        return _station(ship, f.x_ft) if f else "waist"

    def add(line, action, station, trigger, depends, caution=None, tugs=()):
        steps.append(SequenceStep(step=len(steps) + 1, line_number=line, action=action, station=station, crews=1, trigger=trigger, caution=caution,
                                  reference=RULE_REF[action], depends_on=list(depends), duration_min=DURATIONS[action], tug_ids=list(tugs)))
        return len(steps)

    order = [n for n in (2, 5, 3, 4, 1, 6) if n in lines] + sorted(n for n in lines if n not in (1, 2, 3, 4, 5, 6))
    secured: list[int] = []
    prev = None
    for i, n in enumerate(order):
        p = add(n, "pass", st(n), "Bridge orders first line over" if i == 0 else f"Line {order[i - 1]} on its bollard", [prev] if prev else [])
        s = add(n, "secure_pier", "pier", f"Line {n} eye ashore", [p])
        secured.append(s)
        prev = s
        if tugs_holding and lines[n].role in ("breast", None):
            add(n, "hold", st(n), "Tugs holding the ship alongside", [s], caution="Keep this line slack-tended; don't take it to power until the tugs ease off.", tugs=tug_ids)
    allhold = add(None, "hold", "bridge", "All lines on their bollards; tugs ease off" if tugs_holding else "All lines on their bollards", secured, tugs=tug_ids if tugs_holding else ())
    powers = []
    for n in order:
        tp = add(n, "take_to_power", st(n), "Bridge orders lines taken to power", [allhold])
        powers.append(tp)
        if lines[n].parts > 1:
            powers.append(add(n, "double_up", st(n), f"Line {n} tensioned", [tp]))
    add(None, "tend", "bridge", "All lines doubled up and tensioned", powers, caution="Equalize: slack the shortest lines about 1 ft; pre-tension lines over 100 ft.")
    return steps


def _acyclic(steps: list[SequenceStep]) -> list[int]:
    """Step numbers in a dependency cycle (Kahn's algorithm leaves them unprocessed)."""
    indeg = {s.step: 0 for s in steps}
    out: dict[int, list[int]] = {s.step: [] for s in steps}
    for s in steps:
        for d in s.depends_on:
            if d in indeg:
                indeg[s.step] += 1
                out[d].append(s.step)
    q = [k for k, v in indeg.items() if v == 0]
    seen = 0
    while q:
        k = q.pop()
        seen += 1
        for m in out[k]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    return sorted(k for k, v in indeg.items() if v > 0)


def _critical_path(steps: list[SequenceStep]) -> float | None:
    by = {s.step: s for s in steps}
    memo: dict[int, float] = {}
    def f(k, stack=()):
        if k in memo:
            return memo[k]
        if k in stack:
            raise ValueError
        s = by[k]
        memo[k] = (s.duration_min or 0.0) + max((f(d, stack + (k,)) for d in s.depends_on if d in by), default=0.0)
        return memo[k]
    try:
        return round(max(f(k) for k in by), 1)
    except ValueError:
        return None


def load_tug_plan(result_id: str | None, ship_id: str, berth_id: str):
    """The referenced tug plan's assignments, after checking it exists, is a tug plan and belongs to this scenario."""
    if result_id is None:
        return []
    if result_id not in RESULTS:
        raise refdata.InvalidReference(f"tug_plan_result_id '{result_id}' does not exist")
    env = RESULTS[result_id]
    if not str(env.get("model", "")).startswith("mooring.tugs."):
        raise refdata.InvalidReference(f"result '{result_id}' is a {env.get('model')} result, not a tug plan")
    recs = {(r["kind"], r["id"]) for r in (env.get("manifest") or {}).get("records", [])}
    if not recs:
        raise refdata.InvalidReference(f"tug plan '{result_id}' carries no scenario provenance, so it cannot be tied to this ship and berth")
    if ("ship", ship_id) not in recs or ("berth", berth_id) not in recs:
        raise refdata.InvalidReference(f"tug plan '{result_id}' was computed for a different ship or berth")
    out = []
    for a in env["result"].get("assignments", []):
        try:
            refdata.tug(a["tug_id"])
        except refdata.NotFound as e:
            raise refdata.InvalidReference(str(e)) from None
        out.append(TugAssignment(**a))
    return out


def validate(steps: list[SequenceStep], ship: ShipClass, berth, req: SequenceRequest, tug_assignments: list[TugAssignment]):
    """Returns (issues, annotated steps). Does not raise for sequence problems: they are results."""
    issues: list[SequenceIssue] = []
    lines = {l.line_number: l for l in req.config.lines}
    by = {s.step: s for s in steps}

    def add(code, sev, msg, step=None, line=None):
        issues.append(SequenceIssue(code=code, severity=sev, step=step, line_number=line, message=msg))

    if len(by) != len(steps):
        add("DUPLICATE_STEP_NUMBER", "RED", "Step numbers must be unique.")
    for s in steps:
        for d in s.depends_on:
            if d not in by:
                add("UNKNOWN_DEPENDENCY", "RED", f"Step {s.step} depends on missing step {d}.", s.step)
            elif d >= s.step:
                add("ORDER_VIOLATION", "RED", f"Step {s.step} depends on step {d}, which does not come before it.", s.step)
        if s.line_number is not None and s.line_number not in lines:
            add("UNKNOWN_LINE", "RED", f"Step {s.step} refers to line {s.line_number}, which is not in the configuration.", s.step, s.line_number)
    cyc = _acyclic(steps)
    if cyc:
        add("CYCLIC_DEPENDENCY", "RED", f"Steps {cyc} depend on each other in a cycle.")
    # per-line state machine
    stage = {"pass": 1, "secure_pier": 2, "hold": 2, "take_to_power": 3, "double_up": 4, "tend": 4}
    reached: dict[int, dict[str, int]] = {n: {} for n in lines}
    for s in sorted(steps, key=lambda x: x.step):
        n = s.line_number
        if n is None or n not in lines:
            continue
        done = reached[n]
        if s.action in done and s.action not in ("hold", "tend"):
            add("CONFLICTING_ACTION", "RED", f"Line {n}: '{s.action}' appears twice (steps {done[s.action]} and {s.step}).", s.step, n)
        need = {"secure_pier": "pass", "take_to_power": "secure_pier", "double_up": "take_to_power"}.get(s.action)
        if need and need not in done:
            add("CONFLICTING_ACTION", "RED", f"Line {n}: '{s.action}' at step {s.step} before '{need}'.", s.step, n)
        if s.action == "hold" and "take_to_power" in done:
            add("CONFLICTING_ACTION", "RED", f"Line {n} is held at step {s.step} after being taken to power.", s.step, n)
        done.setdefault(s.action, s.step)
    for n, done in reached.items():
        for need in ("pass", "secure_pier", "take_to_power"):
            if need not in done:
                add("MISSING_LINE_ACTION", "RED", f"Line {n} is never '{need}'; the final plan is incomplete.", None, n)
        if lines[n].parts > 1 and "double_up" not in done:
            add("MISSING_LINE_ACTION", "RED", f"Line {n} has {lines[n].parts} parts but is never doubled up.", None, n)
    # resources
    crews_required = max(MIN_CREWS, min(len(lines), 8))
    if req.line_handling_crews < MIN_CREWS:
        add("INSUFFICIENT_CREWS", "RED", f"{req.line_handling_crews} line-handling crews available; at least {MIN_CREWS} are needed.")
    elif req.line_handling_crews < crews_required:
        add("INSUFFICIENT_CREWS", "AMBER", f"{req.line_handling_crews} crews available; this plan wants {crews_required}.")
    known_tugs = {a.tug_id for a in tug_assignments}
    for s in steps:
        for t in s.tug_ids:
            if t not in known_tugs:
                add("UNKNOWN_TUG", "RED", f"Step {s.step} relies on tug {t}, which is not in the referenced tug plan.", s.step)
    # availability and leads
    pfit = {f.fitting_id: f for f in berth.fittings}
    for n, ln in lines.items():
        pf = pfit.get(ln.pier_fitting_id)
        if pf is None or pf.condition != "good" or pf.occupied_by:
            add("LINE_UNAVAILABLE", "RED", f"Line {n}: pier fitting {ln.pier_fitting_id} is unusable (missing, not in good condition, or occupied).", None, n)
            continue
        g = line_geometry(ln, ship, berth, req.config, req.environment.water_level_mllw_ft)
        if g.role == "breast" and g.horiz_angle_deg >= 45:
            add("UNSAFE_LEAD", "AMBER", f"Line {n} leads {g.horiz_angle_deg:.0f} degrees from perpendicular (breast leads should be under 45).", None, n)
    # intermediate states
    specs = {l.spec_id: refdata.line(l.spec_id) for l in lines.values()}
    df = design_factor("II")
    fast: set[int] = set()
    power: set[int] = set()
    tugs_on = bool(tug_assignments)
    annotated: list[SequenceStep] = []
    for s in sorted(steps, key=lambda x: x.step):
        if s.line_number in lines and s.action == "secure_pier":
            fast.add(s.line_number)
        if s.line_number in lines and s.action == "take_to_power":
            power.add(s.line_number)
        if s.line_number is None and s.action == "hold" and tugs_on and len(fast) == len(lines) and s.station == "bridge":
            tugs_on = False   # tugs ease off after every line is on its bollard
        step = s.model_copy(deep=True)
        if s.action in ("secure_pier", "take_to_power") and s.line_number in lines and fast:
            ok, pct, note = _state(ship, berth, req, lines, specs, fast, power, tug_assignments if tugs_on else [], df)
            if ok is None:   # fewer than three lines cannot restrain the hull: expected early on, not evaluable statically
                step.state_ok, step.state_note = None, note
                add("PARTIAL_RESTRAINT", "AMBER", f"After step {s.step} (line {s.line_number} {s.action}): {note}", s.step, s.line_number)
            else:
                step.state_ok, step.state_max_pct, step.state_note = ok, pct, note
                if not ok:
                    add("UNSAFE_INTERMEDIATE_STATE", "RED", f"After step {s.step} (line {s.line_number} {s.action}): {note}", s.step, s.line_number)
        annotated.append(step)
    ok, pct, note = _state(ship, berth, req, lines, specs, set(lines), set(lines), [], df)
    if not ok:
        add("INVALID_FINAL_PLAN", "RED", f"The completed plan does not hold: {note}")
    return issues, annotated, crews_required


def _state(ship, berth, req, lines, specs, fast, power, tugs, df):
    cfg_lines = []
    for n in sorted(fast):
        ln = lines[n].model_copy(deep=True)
        if n not in power:
            ln.pretension_lbf, ln.slack_ft, ln.paid_out_unstretched_length_ft = 0.0, None, None   # on the bollard, not yet tensioned
        cfg_lines.append(ln)
    cfg = req.config.model_copy(update={"lines": cfg_lines})
    try:
        system = eq.build_system(ship, berth, cfg, specs, req.environment, loading="full_load", lines_wet=True, tugs=tugs)
    except eq.SystemError as e:
        return False, None, str(e)
    sol = eq.solve(system)
    if not sol.converged:
        note = f"equilibrium not established with lines {sorted(fast)} fast" + (" and tugs holding" if tugs else "") + f" ({sol.failure})"
        if len(fast) < 3:
            return None, None, note + "; the ship is not yet restrained by these lines, so hold it with tugs or other means until more lines are fast"
        return False, None, note
    el, pct, mode = max(eq.utilization(system, sol.pose, df), key=lambda e: e[1])
    ok = pct <= 100.0
    return ok, round(pct, 1), f"worst {el} at {pct:.0f}% of its {mode} limit" + ("" if ok else " (over limit)")


def _result(req, ship, berth, steps, tug_assignments, result_id_tug):
    issues, annotated, crews_required = validate(steps, ship, berth, req, tug_assignments)
    reds = [i for i in issues if i.severity == "RED"]
    ambers = [i for i in issues if i.severity == "AMBER"]
    reasons = [ValidityReason(code="SEQUENCE_UNREVIEWED", affected_components=["sequence"], message="Draft rule table and estimates; not reviewed by a deck officer or pilot."),
               ValidityReason(code="STATIC_CHECK_ONLY", affected_components=["sequence"], message="Transient safety during handling is not evaluated; M11 is required.")]
    if reds:
        reasons.append(ValidityReason(code="SEQUENCE_HAS_BLOCKING_ISSUES", affected_components=sorted({f"step-{i.step}" for i in reds if i.step} | {"sequence"}), message=f"{len(reds)} blocking issue(s); see issues."))
    state = "invalid" if reds else "limited"
    validity = Validity(state=state, reasons=reasons)
    status = "RED" if reds else "AMBER"
    result = SequenceResult(steps=annotated, crews_required=crews_required, issues=issues, review_status="draft_unreviewed",
                            timing_assumptions=[f"Durations (min): {', '.join(f'{k} {v:g}' for k, v in DURATIONS.items())}; unreviewed estimates. Lines are handled one at a time unless dependencies allow overlap."],
                            limitations=LIMITATIONS, total_duration_min=_critical_path(annotated))
    from mooring.core.envelopes import resolved_inputs_hash
    from mooring.core.schemas import ManifestRecord, ResultManifest
    records = [ManifestRecord(kind="ship", id=ship.class_id), ManifestRecord(kind="berth", id=berth.berth_id)]
    if result_id_tug:
        records.append(ManifestRecord(kind="tug_plan_result", id=result_id_tug))
    manifest = ResultManifest(resolved_inputs_hash=resolved_inputs_hash({"request": req.model_dump(mode="json"), "tug_plan": result_id_tug}),
                              code_version="mooring.planning.sequence@1.0.0", records=records, environment_hash=resolved_inputs_hash(req.environment))
    return envelope(SequenceResponse, model="mooring.planning.sequence", request=req, result=result, status=status_with_validity(status, validity),
                    validity=validity, backend="real", model_version="1.0.0", manifest=manifest,
                    assumptions=["Intermediate states: only the lines then fast are modeled, slack until taken to power; tugs hold until every line is on its bollard.",
                                 *LIMITATIONS])


def sequence(req: SequenceRequest) -> SequenceResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    tug_assignments = load_tug_plan(req.tug_plan_result_id, req.ship_class_id, req.berth_id)
    lines = {l.line_number: l for l in req.config.lines}
    steps = generate_steps(ship, lines, bool(tug_assignments), sorted({a.tug_id for a in tug_assignments}))
    return _result(req, ship, berth, steps, tug_assignments, req.tug_plan_result_id)


def validate_sequence(req: SequenceValidateRequest) -> SequenceResponse:
    ship, berth = refdata.ship(req.ship_class_id), refdata.berth(req.berth_id)
    tug_assignments = load_tug_plan(req.tug_plan_result_id, req.ship_class_id, req.berth_id)
    return _result(req, ship, berth, list(req.steps), tug_assignments, req.tug_plan_result_id)
