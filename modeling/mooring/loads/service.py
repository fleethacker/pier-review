"""M3 HTTP services; the numerical implementation stays independent of envelopes."""

from mooring import refdata
from mooring.core.envelopes import RESULTS, inputs_hash, new_id, status_with_validity, utcnow
from mooring.core.schemas import (
    EnvironmentSnapshot, LoadsRequest, LoadsResponse, PolarPoint, PolarRequest,
    PolarResponse, PolarResult,
)
from mooring.core.schemas import Validity, ValidityReason
from . import coefficients as c
from .helpers import off_pier
from .validity import classify_findings, merge_reasons, wind_basis
from .ufc import compute_loads, ship_inputs
from .warnings import range_findings


def _metadata(ship, loading, depth, water_density, use_gust, current_speed, results, env=None, require_basis=False):
    draft, *_ = ship_inputs(ship, loading, water_density)
    assumptions = [
        "UFC 4-159-03 (2020), Chapter 4; Eq. 4-3 harmonic and symmetric angle folding restored from the earlier UFC edition.",
        "Wind uses the supplied gust speed, assumed to be a 10 m, 30-second gust; the API does not specify gust duration."
        if use_gust else f"Wind uses 10 m, 1-minute sustained speed converted to 30 seconds by {c.SUSTAINED_TO_30S:.3f} (UFC Figure 3-5 synoptic curve, approximate readings 1.31/1.25).",
        "Wind shielding scales all wind forces and moments equally; current is unshielded.",
        "Water depth is actual depth at the ship; water level is not added again.",
        "Current model assumes a wide harbor/channel, level keel, and 15 C salt-water viscosity (Table 4-1); density uses the request.",
        "Yaw uses UFC Tables 4-5/4-10: DDG and CG use destroyer wind / FFG current; CVN and LHD use carrier wind / CVE 55 current. CG is assumed at midships.",
    ]
    estimates = {
        "superstructure_height_ft": "Superstructure height estimated as hull area/LWL + superstructure area/(0.5 LWL); rectangular profile with half-length superstructure.",
        "midship_coefficient": "Midship coefficient estimated as 0.83 by analogy to the UFC Table 4-8 destroyer.",
        "wetted_surface_ft2": "Wetted surface estimated for the requested loading and density with UFC Eq. 4-18.",
        "propeller_expanded_area_ft2": "Propeller expanded area estimated with UFC Eqs. 4-22/4-23, Table 4-7 (unit pitch ratio; LHD uses carrier analogy; unlisted hull types use destroyer analogy).",
    }
    for field, explanation in estimates.items():
        if getattr(ship, field, None) is None or (field == "wetted_surface_ft2" and loading != "full_load"):
            assumptions.append(explanation)
    if ship.provenance.confidence == "estimated":
        assumptions.append(f"Ship geometry is estimated: {ship.provenance.notes or ship.provenance.source}")
    warnings, notes = range_findings(depth, draft, current_speed,
                                     [r.current.coefficients["reynolds"] for r in results])
    assumptions.extend(notes)
    reasons, invalid = [], False
    if env is not None:
        basis = wind_basis(env, use_gust)
        assumptions.extend(basis.notes)
        reasons += basis.reasons
        if require_basis and not basis.verified and not basis.reasons:
            reasons.append(ValidityReason(code="WIND_BASIS_UNVERIFIED", affected_components=["wind"],
                                          message="Wind averaging/gust duration/height are not documented; the legacy assumption was used."))
    for state, reason in classify_findings(warnings):
        reasons.append(reason)
        invalid = invalid or state == "invalid"
    if ship.provenance.confidence not in ("published", "synthetic"):
        reasons.append(ValidityReason(code="REFERENCE_DATA_NOT_QUALIFIED", affected_components=[ship.class_id],
                                      message=f"Ship '{ship.class_id}' geometry is {ship.provenance.confidence} data, not published."))
    reasons = merge_reasons(reasons)
    state = "invalid" if invalid else "limited" if reasons else "valid"
    if invalid:  # an invalid result is RED with explanatory findings
        warnings = [f.model_copy(update={"severity": "RED"}) if f.rule_id == "UFC-DEPTH-RANGE" else f for f in warnings]
    return assumptions, warnings, Validity(state=state, reasons=reasons)


def _manifest(req, ship, env=None):
    from mooring.core import store
    from mooring.core.envelopes import resolved_inputs_hash
    from mooring.core.schemas import ManifestRecord, ResultManifest

    snap = {"request": req.model_dump(mode="json"), "ship": ship.model_dump(mode="json")}
    h = resolved_inputs_hash(snap)
    store.save_snapshot(h, snap)
    return ResultManifest(resolved_inputs_hash=h, code_version="mooring.loads.ufc@1.0.0",
                          records=[ManifestRecord(kind="ship", id=ship.class_id, revision=resolved_inputs_hash(snap["ship"])[:23])],
                          environment_hash=resolved_inputs_hash(env) if env is not None else None)


def _response(cls, req, result, assumptions, warnings, validity, manifest=None):
    base = "RED" if any(w.severity == "RED" for w in warnings) else "AMBER" if warnings else "GREEN"
    response = cls(result_id=new_id("res"), model="mooring.loads.ufc", model_version="1.0.0", backend="real",
                   inputs_hash=inputs_hash(req), computed_at_utc=utcnow(), status=status_with_validity(base, validity),
                   assumptions=assumptions, warnings=warnings, validity=validity, manifest=manifest, result=result)
    RESULTS[response.result_id] = response.model_dump(mode="json")
    return response


def environmental(req: LoadsRequest) -> LoadsResponse:
    ship = refdata.ship(req.ship_class_id)
    result = compute_loads(ship, req.loading, req.heading_true_deg, req.environment, req.water_depth_ft,
                           req.use_gust, req.shielding_factor)
    if req.side_to:
        result.off_pier_component_lbf = off_pier(result.total.fy_lbf, req.side_to)
    assumptions, warnings, validity = _metadata(ship, req.loading, req.water_depth_ft, req.environment.water_density_kgm3,
                                                req.use_gust, req.environment.current_speed_kt, [result],
                                                req.environment, req.require_verified_wind_basis)
    return _response(LoadsResponse, req, result, assumptions, warnings, validity, _manifest(req, ship, req.environment))


def polar(req: PolarRequest) -> PolarResponse:
    ship = refdata.ship(req.ship_class_id)
    points, results = [], []
    for rel in range(0, 360, req.step_deg):
        env = EnvironmentSnapshot(wind_speed_kt=req.wind_speed_kt if req.apply_to != "current" else 0,
                                  wind_gust_kt=req.wind_speed_kt if req.apply_to != "current" else 0,
                                  wind_from_true_deg=rel,
                                  current_speed_kt=req.current_speed_kt if req.apply_to != "wind" else 0,
                                  current_set_true_deg=(rel + 180) % 360, water_level_mllw_ft=0)
        result = compute_loads(ship, req.loading, 0, env, req.water_depth_ft, use_gust=False)
        results.append(result)
        points.append(PolarPoint(rel_deg=rel, **result.total.model_dump()))
    assumptions, warnings, validity = _metadata(ship, req.loading, req.water_depth_ft, env.water_density_kgm3, False,
                                                env.current_speed_kt, results)
    assumptions.append("rel_deg is the direction the wind comes from; current flows the same way as the wind.")
    return _response(PolarResponse, req, PolarResult(points=points), assumptions, warnings, validity, _manifest(req, ship))
