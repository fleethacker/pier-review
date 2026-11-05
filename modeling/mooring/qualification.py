"""Reference-data qualification (S01).

Separates *schema validity* (Pydantic already guarantees finite positive numbers) from *physical-data confidence*
(is this record published and complete enough for the capability asked of it). Pure functions over catalog records;
no solver or API imports, so mechanics and phases can both use it.

Levels: `qualified` (published provenance, nothing missing), `demonstration` (complete but mock/estimated/vision/
synthetic data), `unqualified` (required data missing or inconsistent: a real analysis must not proceed).
Capabilities that need data we do not hold (loading-specific fitting heights, contact curves beyond a linear
stiffness, tug rating certification, dynamic coefficients) are reported as limited or unsupported rather than guessed.
"""

import math
from collections import Counter

from mooring import refdata
from mooring.core.schemas import (
    AssetQualification, Berth, CapabilityRow, CatalogAudit, LineSpec, MooringConfig, QualificationIssue, ShipClass,
    TugSpec,
)

QUALIFYING_CONFIDENCE = {"published"}


def _issue(code: str, message: str, ids: list[str] | None = None, blocking: bool = False) -> QualificationIssue:
    return QualificationIssue(code=code, message=message, element_ids=ids or [], blocking=blocking)


def _level(issues: list[QualificationIssue], confidence: str) -> str:
    if any(i.blocking for i in issues):
        return "unqualified"
    return "qualified" if confidence in QUALIFYING_CONFIDENCE and not issues else "demonstration"


def _dups(ids: list[str]) -> list[str]:
    return sorted(k for k, n in Counter(ids).items() if n > 1)


# ---------- Lines ----------

def line_curve_issues(spec: LineSpec) -> list[QualificationIssue]:
    pts = spec.load_elongation
    issues = []
    if len(pts) < 2:
        return [_issue("CURVE_TOO_SHORT", "Load-elongation curve needs at least two points.", [spec.spec_id], True)]
    loads, strains = [p[0] for p in pts], [p[1] for p in pts]
    if not all(math.isfinite(v) for v in loads + strains):
        issues.append(_issue("CURVE_NOT_FINITE", "Curve has non-finite values.", [spec.spec_id], True))
        return issues
    if pts[0] != (0, 0) and tuple(pts[0]) != (0.0, 0.0):
        issues.append(_issue("CURVE_NOT_FROM_ORIGIN", "Curve must start at [0, 0].", [spec.spec_id], True))
    if any(b <= a for a, b in zip(loads, loads[1:])):
        issues.append(_issue("CURVE_LOAD_NOT_INCREASING", "Load fractions must strictly increase.", [spec.spec_id], True))
    if any(b <= a for a, b in zip(strains, strains[1:])):
        issues.append(_issue("CURVE_NOT_MONOTONE", "Strain must strictly increase with load (tension-only, stiffening or softening).", [spec.spec_id], True))
    if loads[-1] < 1.0:
        issues.append(_issue("CURVE_COVERAGE", f"Curve stops at {loads[-1]:.2f} of MBS; loads up to MBS are not covered.", [spec.spec_id], True))
    if any(l < 0 or l > 1.5 for l in loads) or any(s < 0 for s in strains):
        issues.append(_issue("CURVE_OUT_OF_RANGE", "Load fractions must be in [0, 1.5] and strains non-negative.", [spec.spec_id], True))
    return issues


def qualify_line(spec: LineSpec) -> AssetQualification:
    issues = line_curve_issues(spec)
    if spec.provenance.confidence not in QUALIFYING_CONFIDENCE:
        issues.append(_issue("PROVENANCE_NOT_PUBLISHED", f"MBS and curve come from '{spec.provenance.confidence}' data.", [spec.spec_id]))
    issues.append(_issue("WET_DRY_CURVES_SINGLE", "One stretch curve per spec; wet and dry share it, only strength is scaled.", [spec.spec_id]))
    blocking = any(i.blocking for i in issues)
    return AssetQualification(
        asset_kind="line_spec", asset_id=spec.spec_id, level=_level(issues, spec.provenance.confidence),
        provenance_confidence=spec.provenance.confidence, issues=issues,
        capabilities={"static_mooring": "unsupported" if blocking else "limited"})


# ---------- Ships ----------

def qualify_ship(ship: ShipClass, line_ids: set[str] | None = None) -> AssetQualification:
    from mooring.templates import TemplateUnsupported, ship_template_slots

    issues: list[QualificationIssue] = []
    ids = [f.fitting_id for f in ship.fittings]
    if d := _dups(ids):
        issues.append(_issue("DUPLICATE_SHIP_FITTING", "Duplicate ship fitting ids.", d, True))
    known = {f.fitting_id: f for f in ship.fittings}
    for f in ship.fittings:
        if not f.fitting_id.strip():
            issues.append(_issue("EMPTY_FITTING_ID", "Fitting IDs must not be blank.", [ship.class_id], True))
        if f.paired_chock_id and f.paired_chock_id not in known:
            issues.append(_issue("DANGLING_CHOCK", f"{f.fitting_id} refers to missing chock {f.paired_chock_id}.", [f.fitting_id], True))
        elif f.paired_chock_id:
            chock = known[f.paired_chock_id]
            if chock.kind != "chock" or chock.side not in (f.side, "centerline"):
                issues.append(_issue("INVALID_CHOCK", "A paired chock must be a chock on the same side (or centerline).", [f.fitting_id, chock.fitting_id], True))
        if (f.side == "port" and f.y_ft < 0 or f.side == "starboard" and f.y_ft > 0
                or f.side == "centerline" and f.y_ft != 0):
            issues.append(_issue("FITTING_FRAME_CONFLICT", "Fitting side conflicts with ship-frame +y to port.", [f.fitting_id], True))
        if abs(f.x_ft) > ship.loa_ft / 2 or abs(f.y_ft) > ship.beam_ft / 2:
            issues.append(_issue("FITTING_OUTSIDE_HULL", "Fitting coordinates exceed the declared hull dimensions; verify frame and units.", [f.fitting_id], True))
        if f.max_rope_circ_in is not None and f.max_rope_circ_in <= 0:
            issues.append(_issue("INVALID_ROPE_SIZE_LIMIT", "Maximum rope circumference must be positive.", [f.fitting_id], True))
    no_swl = [f.fitting_id for f in ship.fittings if f.kind in ("bitt", "recessed_bitt", "cleat") and (f.swl_lbf is None or f.swl_lbf <= 0)]
    if no_swl:
        issues.append(_issue("MISSING_SWL", "Bitts/cleats require a positive safe working load.", no_swl, True))
    if not ship.fittings:
        issues.append(_issue("NO_FITTINGS", "No fitting layout: static mooring is unsupported for this class.", [ship.class_id]))
    if _dups([p.push_point_id for p in ship.push_points]):
        issues.append(_issue("DUPLICATE_PUSH_POINT", "Duplicate push point ids.", _dups([p.push_point_id for p in ship.push_points]), True))
    for p in ship.push_points:
        if not p.push_point_id.strip() or abs(p.x_ft) > ship.loa_ft / 2:
            issues.append(_issue("INVALID_PUSH_POINT", "Push points need an ID and a station inside the hull.", [p.push_point_id], True))
    if d := _dups([i.spec_id for i in ship.standard_line_outfit]):
        issues.append(_issue("DUPLICATE_LINE_INVENTORY", "Line inventory specs must be unique; counts cannot be silently combined.", d, True))
    if line_ids is not None:
        missing = [i.spec_id for i in ship.standard_line_outfit if i.spec_id not in line_ids]
        if missing:
            issues.append(_issue("DANGLING_LINE_SPEC", "Standard outfit refers to unknown line specs.", missing, True))
    if len({lc.name for lc in ship.loading_conditions}) != len(ship.loading_conditions):
        issues.append(_issue("DUPLICATE_LOADING", "Duplicate loading condition names.", [ship.class_id], True))
    if not ship.loading_conditions or any(not lc.name.strip() for lc in ship.loading_conditions):
        issues.append(_issue("MISSING_LOADING", "At least one named loading condition is required.", [ship.class_id], True))
    if not ship.provenance.source.strip():
        issues.append(_issue("MISSING_SOURCE", "An input source must be recorded; receipt is not approval.", [ship.class_id], True))
    if not ship.standard_line_outfit:
        issues.append(_issue("MISSING_LINE_INVENTORY", "Line inventory has not been supplied; automatic planning cannot assume available lines.", [ship.class_id]))
    issues.append(_issue("FITTING_HEIGHT_LOADING_UNSPECIFIED",
                         "Fitting heights are above the waterline at an unrecorded reference loading; other loadings are not corrected.",
                         [ship.class_id]))
    issues.append(_issue("NO_DYNAMIC_COEFFICIENTS", "Mass, added mass, damping and maneuvering coefficients are not held.", [ship.class_id]))
    static = "unsupported" if not ship.fittings or any(i.blocking for i in issues) else "limited"
    templates = {}
    for side in ("port", "starboard"):
        try:
            slots = ship_template_slots(ship, side)
            # The current default search uses one line spec per candidate, not an
            # arbitrary mixture of a few pieces of unrelated products.
            available = max((i.count for i in ship.standard_line_outfit), default=0)
            if available < len(slots):
                raise TemplateUnsupported("INSUFFICIENT_LINE_INVENTORY", f"{side} draft needs at least {len(slots)} line parts; inventory has {available}")
        except TemplateUnsupported as exc:
            templates[f"template_{side}"] = "unsupported"
            issues.append(_issue(f"TEMPLATE_{side.upper()}_UNSUPPORTED", str(exc), [ship.class_id]))
        else:
            templates[f"template_{side}"] = static
    environmental = "unsupported" if any(i.code in ("MISSING_LOADING", "DUPLICATE_LOADING") for i in issues) else (
        "limited" if ship.provenance.confidence != "published" else "supported")
    return AssetQualification(
        asset_kind="ship", asset_id=ship.class_id, level=_level(issues, ship.provenance.confidence),
        provenance_confidence=ship.provenance.confidence, issues=issues,
        capabilities={"static_mooring": static, "environmental_loads": environmental,
                      "line_sequence": "limited" if static != "unsupported" and "limited" in templates.values() else "unsupported",
                      **templates, "tug_allocation": "limited" if ship.push_points and not any(i.code in ("DUPLICATE_PUSH_POINT", "INVALID_PUSH_POINT") for i in issues) else "unsupported",
                      "berthing_dynamics": "unsupported"})


# ---------- Berths ----------

def qualify_berth(berth: Berth) -> AssetQualification:
    issues: list[QualificationIssue] = []
    if d := _dups([f.fitting_id for f in berth.fittings]):
        issues.append(_issue("DUPLICATE_PIER_FITTING", "Duplicate pier fitting ids.", d, True))
    if d := _dups([f.fender_id for f in berth.fenders]):
        issues.append(_issue("DUPLICATE_FENDER", "Duplicate fender ids.", d, True))
    xs = [p.x_ft for p in berth.depth_profile]
    if _dups([str(x) for x in xs]):
        issues.append(_issue("DEPTH_PROFILE_DUPLICATE_X", "Depth profile has repeated x.", [berth.berth_id], True))
    if xs and (min(xs) > 0 or max(xs) < berth.face_length_ft):
        issues.append(_issue("DEPTH_COVERAGE", f"Depth profile covers x {min(xs):g}..{max(xs):g} ft, not the whole {berth.face_length_ft:g} ft face; values are held constant beyond it.", [berth.berth_id]))
    out = [f.fitting_id for f in berth.fittings if not 0 <= f.x_ft <= berth.face_length_ft]
    if out:
        issues.append(_issue("FITTING_OUTSIDE_FACE", "Fittings lie outside the berth face length.", out))
    if not any(f.condition == "good" for f in berth.fittings):
        issues.append(_issue("NO_USABLE_FITTINGS", "No pier fitting is in good condition.", [berth.berth_id], True))
    if not berth.fenders:
        issues.append(_issue("NO_FENDERS", "No fenders: ship-to-pier contact cannot be resisted or evaluated.", [berth.berth_id]))
    issues.append(_issue("FENDER_LINEAR_ONLY", "Fenders carry a linear stiffness and an energy rating only; no force-deflection curve or vertical extent.", [berth.berth_id]))
    return AssetQualification(
        asset_kind="berth", asset_id=berth.berth_id, level=_level(issues, berth.provenance.confidence),
        provenance_confidence=berth.provenance.confidence, issues=issues,
        capabilities={"static_mooring": "unsupported" if any(i.blocking for i in issues) else "limited", "approach_ukc": "unsupported"})


# ---------- Tugs ----------

def qualify_tug(tug: TugSpec) -> AssetQualification:
    issues = [_issue("RATING_IS_ESTIMATE" if tug.provenance.confidence != "published" else "RATING_SOURCE_UNVERIFIED",
                     "Bollard pull is not a certified rating on file; do not treat it as one.", [tug.tug_id])]
    return AssetQualification(
        asset_kind="tug", asset_id=tug.tug_id,
        level=_level(issues, tug.provenance.confidence),
        provenance_confidence=tug.provenance.confidence, issues=issues, capabilities={"tug_allocation": "limited"})


# ---------- Catalog and analysis ----------

def _raw_ids(path, key) -> list[str]:
    data = refdata._load(path)
    return [d[key] for d in data]


def audit_catalog() -> CatalogAudit:
    """Catalog-wide integrity: duplicate ids in the source files, dangling references, per-asset qualification."""
    problems: list[QualificationIssue] = []
    for label, ids in (("ship", [refdata._load(p)["class_id"] for p in sorted((refdata.ROOT / "ships").glob("*.yaml"))]),
                       ("line_spec", _raw_ids(refdata.ROOT / "lines.yaml", "spec_id")),
                       ("berth", [refdata._load(p)["berth_id"] for p in sorted((refdata.ROOT / "berths").glob("*.yaml"))]),
                       ("tug", _raw_ids(refdata.ROOT / "tugs.yaml", "tug_id"))):
        if d := _dups(ids):
            problems.append(_issue("DUPLICATE_ID", f"Duplicate {label} ids in the catalog source.", d, True))
    line_ids = {s.spec_id for s in refdata.lines()}
    assets = [qualify_line(s) for s in refdata.lines()] + [qualify_ship(s, line_ids) for s in refdata.ships()] \
        + [qualify_berth(b) for b in refdata.berths()] + [qualify_tug(t) for t in refdata.tugs()]
    return CatalogAudit(ok=not problems and all(a.level != "unqualified" for a in assets if a.asset_kind != "ship"),
                        problems=problems, assets=assets)


def analysis_issues(ship: ShipClass, berth: Berth, config: MooringConfig, specs: dict[str, LineSpec]) -> list[QualificationIssue]:
    """Issues that bear on one specific mooring plan. Blocking issues make the analysis invalid."""
    issues: list[QualificationIssue] = []
    sfit = {f.fitting_id: f for f in ship.fittings}
    pfit = {f.fitting_id: f for f in berth.fittings}
    for ln in config.lines:
        n = f"line-{ln.line_number}"
        spec = specs.get(ln.spec_id)
        if spec is not None:
            for i in line_curve_issues(spec):
                issues.append(_issue(i.code, i.message, [n], True))
        sf, pf = sfit.get(ln.ship_fitting_id), pfit.get(ln.pier_fitting_id)
        if sf is None:
            issues.append(_issue("UNKNOWN_SHIP_FITTING", f"{ln.ship_fitting_id} is not on {ship.class_id}.", [n, ln.ship_fitting_id], True))
        elif sf.swl_lbf is None and sf.kind != "chock":
            issues.append(_issue("MISSING_FITTING_RATING", f"{sf.fitting_id} has no safe working load; its utilization is unknown.", [sf.fitting_id], True))
        if pf is None:
            issues.append(_issue("UNKNOWN_PIER_FITTING", f"{ln.pier_fitting_id} is not on {berth.berth_id}.", [n, ln.pier_fitting_id], True))
        if ln.chock_id and (ln.chock_id not in sfit or sfit[ln.chock_id].kind != "chock"):
            issues.append(_issue("INVALID_CHOCK", f"chock_id {ln.chock_id} is not a chock on {ship.class_id}.", [n, ln.chock_id], True))
    if not berth.fenders:
        issues.append(_issue("NO_FENDERS", "No fenders on this berth: contact with the pier face cannot be evaluated.", [berth.berth_id]))
    if not ship.fittings:
        issues.append(_issue("NO_FITTINGS", f"{ship.class_id} has no fitting layout.", [ship.class_id], True))
    return issues


def qualification_reasons(ship: ShipClass, berth: Berth, specs: dict[str, LineSpec]) -> list[tuple[str, str, list[str]]]:
    """Non-blocking confidence reasons (code, message, ids) for validity 'limited'."""
    out = []
    for kind, asset, conf in (("ship", ship.class_id, ship.provenance.confidence), ("berth", berth.berth_id, berth.provenance.confidence),
                              *(("line_spec", s.spec_id, s.provenance.confidence) for s in specs.values())):
        if conf not in QUALIFYING_CONFIDENCE:
            out.append(("REFERENCE_DATA_NOT_QUALIFIED", f"{kind} '{asset}' is {conf} data, not published/qualified.", [asset]))
    out.append(("FITTING_HEIGHT_LOADING_UNSPECIFIED", "Ship fitting heights are not corrected for the requested loading.", [ship.class_id]))
    return out


def capability_matrix() -> list[CapabilityRow]:
    """What each capability is, honestly, today. Backend 'real' describes the implementation, never certification."""
    mock = "mock"
    return [
        CapabilityRow(capability="Environmental loads", module="M3", backend="real", qualification="demonstration",
                      limitations=["UFC 4-159-03 Chapter 4 formulas; seed ship geometry is estimated or mock data.", "Wind basis documented only when the snapshot carries metadata.",
                                   "Static wind and current only; wave and wake loads are not evaluated."]),
        CapabilityRow(capability="Static mooring equilibrium, limiting wind, tide sweep", module="M4", backend="real", qualification="demonstration",
                      limitations=["Rigid-body 3-DOF quasi-static; no heave/roll/pitch or dynamics.", "NSTM rule subset: see GET /rules coverage; paragraph references not re-verified.",
                                   "Fitting heights not corrected for loading; fenders linear and parallel-body only."],
                      blockers=["Published fitting layouts, line strengths and fender curves are not on file."]),
        CapabilityRow(capability="Gust risk (exceedance, timeline, alerts)", module="M5", backend="real", qualification="unqualified",
                      limitations=["Synthetic and fitted artifacts remain unqualified: probabilities are scenario outputs only.", "No forecast error, tide error or storm winds."],
                      blockers=["Fitted and held-out-validated station data (minimum-data policy not met)."]),
        CapabilityRow(capability="Tug allocation, holding plans, berthing windows", module="M6", backend="real", qualification="demonstration",
                      limitations=["Catalog bollard pulls are estimates, not certified.", "Normal push-point forces only; surge cannot be supplied.", "No transient or approach maneuvering."],
                      blockers=["Certified tug ratings and push-point limits."]),
        CapabilityRow(capability="Line-plan search and line-handling sequence", module="M7", backend="real", qualification="demonstration",
                      limitations=["Bounded search; no feasible plan found is not proof none exists.", "Sequence is a draft_unreviewed static check; transients need M11."],
                      blockers=["Subject-matter review of sequence rules (deck officer or pilot)."]),
        CapabilityRow(capability="Advance forecast docking assessment", module="M4/F24", backend="real", qualification="demonstration",
                      limitations=["Supplied coincident snapshots, at least 24-hour lead, static fixed-installation checks only.",
                                   "Complete public forecast composition is not wired; unresolved inputs cannot support an arrival.",
                                   "A supported-limited window is not maneuvering or line-handling approval."],
                      blockers=["Qualified vessel/pier assets, applicable forecast/current depth evidence, and pilot/deck-officer review."]),
        CapabilityRow(capability="Berthing dynamics integrator", module="M11", backend="real", qualification="unqualified",
                      limitations=["RK4 batch and interactive simulation with explicit synthetic body parameters; real vessel dynamics are unqualified.", "Quasi-static M3 loads; no relative-velocity effects."],
                      blockers=["Mass, added mass, damping and maneuvering coefficients for a real hull.", "Independently sourced contact benchmark.", "Subject-matter review and certified tug response data."]),
        CapabilityRow(capability="Approach planner", module="M12", backend=mock, qualification=mock,
                      blockers=["Chart source/edition, datum transformation and sourced squat formulation (S18/S19)."]),
        CapabilityRow(capability="Environment: deterministic replay", module="M1", backend="real", qualification="demonstration",
                      limitations=["Explicit recorded-fixture scenarios and /ws/env replay are wired; the bundled fixture is labeled synthetic, not observed data."]),
        CapabilityRow(capability="Environment: live providers (CO-OPS, NWS, CBOFS)", module="M1", backend="real", qualification="demonstration",
                      limitations=["CO-OPS observations are opt-in; default operation remains labeled mock.",
                                   "NWS and CBOFS readers exist, but a complete composed forecast is unavailable."],
                      blockers=["Pier applicability, current-layer selection, forecast composition and publication-time evidence."]),
        CapabilityRow(capability="Telemetry ingest", module="M13", backend="real", qualification="demonstration",
                      limitations=["NMEA 0183 MWV/HDT/VTG/GGA/DPT subset plus registered load cells; no AIS or NMEA 2000.", "Sensor registry must be configured; optional shared-key auth only."],
                      blockers=["Deployment controls (S21) before connecting real feeds."]),
    ]
