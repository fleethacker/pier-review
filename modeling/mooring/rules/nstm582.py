"""NSTM 582 rule registry used by the compliance checker (module M4), plus UFC load-model validity rules.

Rule IDs are stable: safety sheets cite them. Add a rule here with a test case. References are paragraph and
table numbers only; do not paste NSTM text into this repo (Distribution Statement B).
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from mooring.core.geometry import LineGeometry
from mooring.core.schemas import (
    Berth,
    EnvironmentSnapshot,
    Finding,
    LineResult,
    LineSpec,
    PierFittingResult,
    Rule,
    ShipClass,
    ShipFittingResult,
)

RULES: list[Rule] = [
    Rule(rule_id="LINE-WLL", title="Line tension within working load limit (MBS / design factor)", severity="RED",
         reference="NSTM 582-1.2.3.3, 582-3.3.2, 582-2.4.2.i", applies_to="line", implemented=True),
    Rule(rule_id="LINE-MBS", title="Line tension below breaking strength", severity="RED",
         reference="NSTM 582-3.3.2", applies_to="line", implemented=True),
    Rule(rule_id="PIER-FITTING-CAP", title="Pier fitting load within rated capacity", severity="RED",
         reference="NSTM Table 582-5-6", applies_to="pier_fitting", implemented=True),
    Rule(rule_id="SHIP-BITT-SWL", title="Ship bitt load within safe working load", severity="RED",
         reference="NSTM 582-3.2.1.2, Tables 582-5-3/4", applies_to="ship_fitting", implemented=True),
    Rule(rule_id="MIN-LINES", title="At least one breast and one spring line forward and aft", severity="RED",
         reference="NSTM 582-2.4.6.1", applies_to="plan", implemented=True),
    Rule(rule_id="MST-ENV", title="Environment within the ship's Mooring Service Type limits", severity="RED",
         reference="NSTM 582-1.2.2, Table 582-1-1", applies_to="environment", implemented=True),
    Rule(rule_id="LEAD-45", title="Breast line lead under 45 degrees from perpendicular", severity="AMBER",
         reference="NSTM 582-2.4.4.1.a.3", applies_to="line", implemented=True),
    Rule(rule_id="ONE-PER-FITTING", title="One line per pier fitting, except opposing springs", severity="AMBER",
         reference="NSTM 582-2.4.4.1.b.3", applies_to="pier_fitting", implemented=True),
    Rule(rule_id="CLEAT-USE", title="Cleats only for spring lines, and only when no bollard is available",
         severity="AMBER", reference="NSTM 582-2.4.4.1.b.2, 582-2.3.2", applies_to="pier_fitting", implemented=True),
    Rule(rule_id="NO-MIXED-LINES", title="No mixing of line materials or constructions", severity="AMBER",
         reference="NSTM 582-2.4.4.1.c.3, 582-3.2.2.5", applies_to="plan", implemented=True),
    Rule(rule_id="SHORT-LINE", title="Lines under 50 ft carry more load; slack about 1 ft", severity="AMBER",
         reference="NSTM 582-2.4.4.1.c.2", applies_to="line", implemented=True),
    Rule(rule_id="LONG-LINE-PRETENSION", title="Pre-tension lines over 100 ft", severity="INFO",
         reference="NSTM 582-2.4.4.1.c.2", applies_to="line", implemented=True),
    Rule(rule_id="LINE-SLOPE", title="Keep the vertical angle of lines shallow", severity="INFO",
         reference="NSTM 582-2.4.4.1.a.5", applies_to="line", implemented=True),
    Rule(rule_id="BOW-POSITION", title="Bow about 60 ft from the forward-most pier fitting used", severity="INFO",
         reference="NSTM 582-2.5.2", applies_to="plan", implemented=True),
    Rule(rule_id="PARTS-CAPACITY", title="Two-part tanker moor holds about 2/3 of a three-part moor", severity="INFO",
         reference="NSTM 582-1.2.4.3", applies_to="plan", implemented=True),
    Rule(rule_id="NESTED-MST", title="Nested moorings planned to MST II", severity="AMBER",
         reference="NSTM 582-2.1.4.1", applies_to="plan", implemented=False),
    Rule(rule_id="TUG-HOLD-LINES", title="Don't over-tighten initial lines while tugs hold the ship", severity="AMBER",
         reference="NSTM 582-2.2.3.1", applies_to="sequence", implemented=True),
    Rule(rule_id="BERTHING-SPEED", title="Berthing speed at or below 1.5 ft/s (0.9 kt)", severity="RED",
         reference="NSTM Table 582-2-3", applies_to="berthing", implemented=False),
    Rule(rule_id="FITTING-CONDITION", title="Don't use suspect, damaged or occupied fittings", severity="RED",
         reference="NSTM 582-2.3.1", applies_to="pier_fitting", implemented=True),
    # Load-model validity (UFC 4-159-03), raised by mooring.loads.range_findings, not by NSTM checks.
    Rule(rule_id="UFC-DEPTH-RANGE", title="Water depth at or below draft: current coefficient clamped at T/d = 1",
         severity="AMBER", reference="UFC 4-159-03 Figure 4-9; Eq. 4-10", applies_to="environment", implemented=True),
    Rule(rule_id="UFC-CURRENT-SPEED", title="Current above the 1.5 m/s range of the current-force coefficient",
         severity="AMBER", reference="UFC 4-159-03 4-5.1", applies_to="environment", implemented=True),
    Rule(rule_id="UFC-LOW-REYNOLDS", title="Very low current speed: friction Reynolds number floored",
         severity="AMBER", reference="UFC 4-159-03 Eqs. 4-19/4-20", applies_to="environment", implemented=True),
]

# Audit (S01). Coverage says what the code checks; `source_verified` stays False because NSTM 582 is not kept in
# this repo (distribution restriction), so no paragraph or table here has been re-verified against the edition.
_AUDIT: dict[str, tuple[str, str]] = {
    "LINE-WLL": ("implemented", "Uses MBS x parts x wet factor / design factor; design factor by MST only."),
    "LINE-MBS": ("implemented", "Same tension as LINE-WLL; no dynamic or snatch allowance."),
    "PIER-FITTING-CAP": ("partial", "Compares resultant to nominal capacity; ignores horizontal/45-degree ratings."),
    "SHIP-BITT-SWL": ("partial", "Skipped where the ship fitting has no SWL; that is reported as missing data."),
    "MIN-LINES": ("partial", "Role-based count; does not check nested or special arrangements."),
    "MST-ENV": ("partial", "Wind/current envelope only; current uses the broadside component for MST II+."),
    "LEAD-45": ("implemented", "Breast lines only; horizontal angle from perpendicular."),
    "ONE-PER-FITTING": ("partial", "Opposing-spring exception not evaluated."),
    "CLEAT-USE": ("partial", "Bollard availability is not checked."),
    "NO-MIXED-LINES": ("implemented", "Material and construction compared across the plan."),
    "SHORT-LINE": ("partial", "Length threshold only; slack not measured."),
    "LONG-LINE-PRETENSION": ("partial", "Advisory when no pretension is given."),
    "LINE-SLOPE": ("implemented", "Advisory threshold of 30 degrees."),
    "BOW-POSITION": ("partial", "Advisory; distance rule only."),
    "PARTS-CAPACITY": ("partial", "Advisory; does not compute reeving capacity."),
    "NESTED-MST": ("unsupported", "No nesting model; do not claim compliance."),
    "TUG-HOLD-LINES": ("partial", "Sequence-level advisory."),
    "BERTHING-SPEED": ("unsupported", "No berthing-speed evaluation until M11 qualification."),
    "FITTING-CONDITION": ("implemented", "Uses catalog condition and occupancy flags only."),
    "UFC-DEPTH-RANGE": ("implemented", "Load-model validity, not an NSTM rule."),
    "UFC-CURRENT-SPEED": ("implemented", "Load-model validity, not an NSTM rule."),
    "UFC-LOW-REYNOLDS": ("implemented", "Load-model validity, not an NSTM rule."),
}
for _r in RULES:
    _r.coverage, _r.applicability = _AUDIT[_r.rule_id][0], _AUDIT[_r.rule_id][1]  # type: ignore[assignment]

RULES_BY_ID = {r.rule_id: r for r in RULES}

# Mooring Service Type limits (NSTM Table 582-1-1): list of (max wind kt, max current kt) alternatives.
MST_LIMITS: dict[str, list[tuple[float, float]]] = {
    "I": [(34, 1.0)],
    "II": [(64, 2.0)],
    "IIA": [(50, 1.5), (64, 1.0)],
    "III": [(90, 2.0)],
}

DESIGN_FACTOR = {"I": 3.0, "II": 3.0, "IIA": 3.0, "III": 2.5}


def design_factor(mst: str) -> float:
    return DESIGN_FACTOR[mst]


@dataclass
class CheckContext:
    ship: ShipClass
    berth: Berth
    env: EnvironmentSnapshot
    mst: str
    heading_true_deg: float
    geometries: list[LineGeometry]
    line_results: list[LineResult]
    specs: dict[str, LineSpec]
    pier_results: list[PierFittingResult]
    ship_results: list[ShipFittingResult]
    bow_x_berth_ft: float
    bow_dir: int  # +1 if the bow points toward berth +x (starboard side to), else -1
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule_id: str, severity: str, elements: list[str], message: str) -> None:
        self.findings.append(
            Finding(rule_id=rule_id, severity=severity, element_ids=elements, message=message,
                    reference=RULES_BY_ID[rule_id].reference)
        )


def check_all(ctx: CheckContext) -> list[Finding]:
    for check in (_lines, _fittings, _min_lines, _mst_env, _one_per_fitting, _mixed, _bow_position, _parts):
        check(ctx)
    return ctx.findings


def _lines(ctx: CheckContext) -> None:
    for g, r in zip(ctx.geometries, ctx.line_results):
        eid = f"line-{r.line_number}"
        if r.pct_mbs >= 100:
            ctx.add("LINE-MBS", "RED", [eid], f"Line {r.line_number} at {r.pct_mbs:.0f}% of breaking strength.")
        if r.pct_wll > 100:
            ctx.add("LINE-WLL", "RED", [eid], f"Line {r.line_number} at {r.pct_wll:.0f}% of working load limit.")
        elif r.pct_wll > 80:
            ctx.add("LINE-WLL", "AMBER", [eid], f"Line {r.line_number} at {r.pct_wll:.0f}% of working load limit.")
        if g.role == "breast" and g.horiz_angle_deg >= 45:
            ctx.add("LEAD-45", "AMBER", [eid],
                    f"Breast line {r.line_number} leads {g.horiz_angle_deg:.0f} deg from perpendicular "
                    f"({g.breast_efficiency:.0%} efficient).")
        if g.length_ft < 50:
            ctx.add("SHORT-LINE", "AMBER", [eid],
                    f"Line {r.line_number} is {g.length_ft:.0f} ft; short lines take more load. Slack about 1 ft.")
        elif g.length_ft > 100 and not g.line.pretension_lbf:
            ctx.add("LONG-LINE-PRETENSION", "INFO", [eid],
                    f"Line {r.line_number} is {g.length_ft:.0f} ft; pre-tension it so it shares load.")
        if g.vert_angle_deg > 30:
            ctx.add("LINE-SLOPE", "INFO", [eid],
                    f"Line {r.line_number} slopes {g.vert_angle_deg:.0f} deg; steep lines resist less horizontal load.")


def _fittings(ctx: CheckContext) -> None:
    pier = {f.fitting_id: f for f in ctx.berth.fittings}
    for pr in ctx.pier_results:
        f = pier[pr.fitting_id]
        if pr.pct > 100:
            ctx.add("PIER-FITTING-CAP", "RED", [pr.fitting_id], f"{pr.fitting_id} at {pr.pct:.0f}% of rated capacity.")
        elif pr.pct > 80:
            ctx.add("PIER-FITTING-CAP", "AMBER", [pr.fitting_id], f"{pr.fitting_id} at {pr.pct:.0f}% of rated capacity.")
        if f.condition == "do_not_use":
            ctx.add("FITTING-CONDITION", "RED", [pr.fitting_id], f"{pr.fitting_id} is marked do-not-use.")
        elif f.condition == "suspect":
            ctx.add("FITTING-CONDITION", "AMBER", [pr.fitting_id], f"{pr.fitting_id} is marked suspect; inspect first.")
        if f.occupied_by:
            ctx.add("FITTING-CONDITION", "AMBER", [pr.fitting_id], f"{pr.fitting_id} already holds {f.occupied_by}.")
        if f.kind.startswith("cleat"):
            roles = {g.role for g in ctx.geometries if g.pier_fitting.fitting_id == pr.fitting_id}
            if roles - {"spring_fwd", "spring_aft"}:
                ctx.add("CLEAT-USE", "AMBER", [pr.fitting_id], f"{pr.fitting_id} is a cleat; use cleats for springs only.")
            else:
                ctx.add("CLEAT-USE", "INFO", [pr.fitting_id], f"{pr.fitting_id} is a cleat; prefer a bollard if one is free.")
    for sr in ctx.ship_results:
        if sr.pct is not None and sr.pct > 100:
            ctx.add("SHIP-BITT-SWL", "RED", [sr.fitting_id], f"{sr.fitting_id} at {sr.pct:.0f}% of safe working load.")
        elif sr.pct is not None and sr.pct > 80:
            ctx.add("SHIP-BITT-SWL", "AMBER", [sr.fitting_id], f"{sr.fitting_id} at {sr.pct:.0f}% of safe working load.")


def _min_lines(ctx: CheckContext) -> None:
    holding = {"bow", "breast", "stern"}
    fwd_hold = any(g.role in holding and g.lead_point.x_ft > 0 for g in ctx.geometries)
    aft_hold = any(g.role in holding and g.lead_point.x_ft <= 0 for g in ctx.geometries)
    has_fwd_spring = any(g.role == "spring_fwd" for g in ctx.geometries)
    has_aft_spring = any(g.role == "spring_aft" for g in ctx.geometries)
    missing = []
    if not fwd_hold:
        missing.append("a breast (or bow) line forward")
    if not aft_hold:
        missing.append("a breast (or stern) line aft")
    if not has_aft_spring:
        missing.append("a spring leading aft")
    if not has_fwd_spring:
        missing.append("a spring leading forward")
    if missing:
        ctx.add("MIN-LINES", "RED", [], "Plan is missing " + ", ".join(missing) + ".")


def _mst_env(ctx: CheckContext) -> None:
    rel_c = math.radians((ctx.env.current_set_true_deg - ctx.heading_true_deg) % 360)
    broadside = ctx.env.current_speed_kt * abs(math.sin(rel_c))
    current = ctx.env.current_speed_kt if ctx.mst == "I" else broadside
    wind = ctx.env.wind_speed_kt
    limits = MST_LIMITS[ctx.mst]
    if not any(wind <= w and current <= c for w, c in limits):
        ctx.add("MST-ENV", "RED", [],
                f"Wind {wind:.0f} kt / current {current:.1f} kt exceeds MST {ctx.mst} limits {limits}.")
    elif not any(wind <= 0.9 * w and current <= 0.9 * c for w, c in limits):
        ctx.add("MST-ENV", "AMBER", [], f"Wind {wind:.0f} kt / current {current:.1f} kt within 10% of MST {ctx.mst} limits.")


def _one_per_fitting(ctx: CheckContext) -> None:
    by_fitting: dict[str, list[LineGeometry]] = defaultdict(list)
    for g in ctx.geometries:
        by_fitting[g.pier_fitting.fitting_id].append(g)
    for fid, gs in by_fitting.items():
        if len(gs) < 2:
            continue
        roles = sorted(g.role for g in gs)
        if len(gs) == 2 and roles == ["spring_aft", "spring_fwd"]:
            continue
        ctx.add("ONE-PER-FITTING", "AMBER", [fid],
                f"{fid} holds lines {', '.join(str(g.line.line_number) for g in gs)}; use one line per fitting.")


def _mixed(ctx: CheckContext) -> None:
    kinds = {(ctx.specs[g.line.spec_id].material, ctx.specs[g.line.spec_id].construction) for g in ctx.geometries}
    if len(kinds) > 1:
        desc = ", ".join(f"{m} {c.replace('_', ' ')}" for m, c in sorted(kinds))
        ctx.add("NO-MIXED-LINES", "AMBER", [], f"Plan mixes {desc}; stiffer lines will take most of the load.")


def _bow_position(ctx: CheckContext) -> None:
    """Rule of thumb: the bow about 60 ft short of the forward-most pier fitting used (flag outside 20-100 ft)."""
    if not ctx.geometries:
        return
    ahead = max(ctx.bow_dir * (g.pier_fitting.x_ft - ctx.bow_x_berth_ft) for g in ctx.geometries)
    if not 20 <= ahead <= 100:
        ctx.add("BOW-POSITION", "INFO", [],
                f"Forward-most pier fitting is {ahead:.0f} ft ahead of the bow; about 60 ft balances loads best.")


def _parts(ctx: CheckContext) -> None:
    tanker = [g.line.line_number for g in ctx.geometries if g.line.parts == 2]
    if tanker:
        ctx.add("PARTS-CAPACITY", "INFO", [f"line-{n}" for n in tanker],
                "Two-part (tanker) lines hold about 2/3 of a doubled-up (three-part) line.")
