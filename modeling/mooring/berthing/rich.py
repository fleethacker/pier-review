"""S1: rm0-v1 scene and rich frames from actual BerthingModel state.

Interface contract shared by the session protocol (sim_sessions.py / ws.py) and this module.
Pure functions: they read model state and never advance, mutate or reschedule the simulation.

Rules (docs/MOTION_FRAME_DESIGN.md, docs/MASTER_PLAN.md S1):
- Every value comes from the simulator's current state or the immutable scenario inputs.
  Anything not modeled is null with availability "unavailable"/"not_simulated", never zero.
- Provenance kind is "estimated" (real integrator, synthetic unqualified body, seed catalog data);
  never "qualified". Component and frame validity are "limited" (or "invalid" when the model is).
- Surge, sway, yaw are "simulated". Heave, roll, pitch are "not_simulated" (S3 adds heave).
- Tug kinematics are not modeled: tug position/velocity/acceleration stay null; forces, push point,
  contact position, mode and utilization come from the active ramp and push-point assignment.
- Waves: all four components unavailable (not a zero-wave claim), in environment and forces.
- Berth axes for positions and forces; ship-local axes for scene hull outline and ship fittings.
  Yaw moments are about the instantaneous ship reference point, +counterclockwise.
"""

import hashlib
import json
import math

from mooring.core.geometry import PIER_FITTING_HEIGHT_FT
from mooring.core.schemas import SimFrame, SimScene
from mooring.mechanics.dynamics import _deriv
from .s3_vertical import vertical_state
from mooring.mechanics.pose import force_wrench, force_wrench_at

SCHEMA_VERSION = "rm0-v1"
SOURCE = "mooring.berthing.simulator synthetic-demonstration-v1"
WAVE_NAMES = ("ocean_swell", "local_chop", "ship_wake", "tug_wake")


# ---------- evidence helpers ----------

def _validity(code: str, message: str, component: str) -> dict:
    return {"state": "limited", "reasons": [{"code": code, "message": message, "affected_components": [component]}]}


def _static(component: str, source: str, notes: list[str] | None = None) -> dict:
    """Scene element evidence: estimated seed reference data, limited."""
    return {"availability": "available",
            "validity": _validity("SEED_REFERENCE_DATA", "Seed reference data; unqualified estimate.", component),
            "provenance": {"kind": "estimated", "source": source, "references": [], "notes": notes or []}}


def _live(component: str) -> dict:
    """Frame element evidence: real integrator output on a synthetic, unqualified body."""
    return {"availability": "available",
            "validity": _validity("SYNTHETIC_UNQUALIFIED_DYNAMICS",
                                  "Synthetic unqualified demonstration dynamics with seed reference data.", component),
            "provenance": {"kind": "estimated", "source": SOURCE, "references": [], "notes": []}}


def _wave(component: str, what: str) -> dict:
    return {"availability": "unavailable",
            "validity": {"state": "unknown", "reasons": [{"code": "WAVE_SOURCE_UNAVAILABLE",
                "message": f"No wave source supplied; not a zero-{what} claim.", "affected_components": [component]}]},
            "provenance": {"kind": "unknown", "source": "no wave source or wave model", "references": [],
                           "notes": ["Waves and wakes are not modeled by this simulator."]}}


def _pos(x, y, z=None) -> dict:
    return {"x_ft": x, "y_ft": y, "z_mllw_ft": z}


def _force(x, y, z=None) -> dict:
    return {"x_lbf": x, "y_lbf": y, "z_lbf": z}


# ---------- scene ----------

def _ship_y(model, side: str) -> float:
    return model.ship.beam_ft / 2 if side == "port" else -model.ship.beam_ft / 2


def _hull_outline(model) -> list[dict]:
    """Parametric display planform: square stern, parallel midbody, tapered bow, centered on midships."""
    half_l, half_b = model.ship.loa_ft / 2, model.ship.beam_ft / 2
    taper = half_l - 0.2 * model.ship.loa_ft
    pts = [(-half_l, -half_b), (taper, -half_b), (taper + 0.12 * model.ship.loa_ft, -0.6 * half_b), (half_l, 0.0),
           (taper + 0.12 * model.ship.loa_ft, 0.6 * half_b), (taper, half_b), (-half_l, half_b)]
    return [{"x_ft": x, "y_ft": y, "z_ft": 0.0} for x, y in pts]


def _scene_content(model) -> dict:
    ship, berth = model.ship, model.berth
    ship_src = f"reference data {ship.class_id}"
    berth_src = f"reference data {berth.berth_id}"
    deck = berth.deck_height_mllw_ft
    ship_fittings = [{**_static(f.fitting_id, ship_src), "fitting_id": f.fitting_id, "kind": f.kind,
                      "capacity_lbf": f.swl_lbf, "position": {"x_ft": f.x_ft, "y_ft": f.y_ft, "z_ft": f.z_ft}}
                     for f in ship.fittings]
    ship_fittings += [{**_static(p.push_point_id, ship_src,
                                 ["x from reference data; y is +/- beam/2 by side (parametric); z not given."]),
                       "fitting_id": p.push_point_id, "kind": "tug_push_point", "capacity_lbf": None,
                       "position": {"x_ft": p.x_ft, "y_ft": _ship_y(model, p.side), "z_ft": None}}
                      for p in ship.push_points]
    return {
        "berth_id": berth.berth_id, "ship_class_id": ship.class_id, "loading": model.sc.loading,
        "side_to": model.sc.side_to, "ship_x_ft": model.system.frame.ref_x_ft,
        "config": model.cfg.model_dump(mode="json"),
        "face_bearing_true_deg": berth.face_bearing_true_deg, "deck_height_mllw_ft": deck,
        "berth_outline": [],
        "ship_hull_outline": _hull_outline(model),
        "ship_fittings": ship_fittings,
        "pier_fittings": [{**_static(f.fitting_id, berth_src), "fitting_id": f.fitting_id, "kind": f.kind,
                           "capacity_lbf": f.capacity_nominal_lbf,
                           "position": _pos(f.x_ft, f.y_ft, deck + PIER_FITTING_HEIGHT_FT)} for f in berth.fittings],
        "fenders": [{**_static(f.fender_id, berth_src), "fender_id": f.fender_id, "position": _pos(f.x_ft, 0.0, None),
                     "length_ft": f.length_ft, "standoff_ft": f.standoff_ft} for f in berth.fenders],
        "depth_profile": [{**_static("depth", berth_src), "position": _pos(p.x_ft, 0.0, None),
                           "depth_mllw_ft": p.depth_mllw_ft} for p in sorted(berth.depth_profile, key=lambda p: p.x_ft)],
    }


def scene_id_for(model) -> tuple[str, str]:
    """Deterministic (scene_id, revision) from the scene content hash; same inputs give the same id."""
    blob = json.dumps(_scene_content(model), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "scene_" + hashlib.sha256(blob.encode()).hexdigest()[:16], "1"


def build_scene(model) -> SimScene:
    """Static scene for this model: berth outline/deck/fittings/fenders/depth, ship hull outline/fittings."""
    scene_id, revision = scene_id_for(model)
    content = _scene_content(model)
    for key in ("side_to", "ship_x_ft", "config"):   # identity inputs hashed into the id; not SimScene fields
        content.pop(key)
    sources = f"reference data {model.berth.berth_id}; reference data {model.ship.class_id}"
    notes = [
        "Seed reference data and a synthetic demonstration body; not qualified for any vessel.",
        "berth_outline is empty: reference data has no pier planform, and none is invented.",
        "ship_hull_outline is parametric display geometry (square stern, parallel midbody, tapered bow from LOA and "
        "beam), centered on midships; it is not a hull-lines drawing.",
        "Push points sit at y = +/- beam/2 by side (parametric); their z is not given.",
        "Fenders are placed at the pier face (y = 0); their standoff_ft is the face-to-hull distance.",
        "depth_profile samples are positioned at the pier face (y = 0); depth varies with x only in reference data.",
    ]
    return SimScene.model_validate({
        **_static("scene", sources, notes), **content, "scene_id": scene_id, "revision": revision})


# ---------- frame ----------

def _tug_states(model, s, t, pose) -> list[dict]:
    frame, out = model.system.frame, []
    for tid in sorted(model.ramps):
        tug, pp, (lo, hi) = model.anchors[tid]
        f, target = model.tug_force(tid, t), model.ramps[tid][2]
        side_y = _ship_y(model, pp.side)
        ax, ay = frame.vector_to_berth(0.0, f, pose)
        cx, cy = frame.vector_to_berth(0.0, target, pose)
        toward_centerline = f < 0 if side_y > 0 else f > 0
        mode = "standby" if f == 0 else "push" if toward_centerline else "pull"
        limit = hi if f > 0 else abs(lo)
        px, py = frame.to_berth(pp.x_ft, side_y, pose)
        out.append({**_live(tid), "tug_id": tid, "position": None, "heading_true_deg": None, "velocity": None,
                    "acceleration": None, "commanded_force": _force(cx, cy), "actual_force": _force(ax, ay),
                    "push_point_id": pp.push_point_id, "contact_position": _pos(px, py), "mode": mode,
                    "contact_state": {"push": "contact", "pull": "line_made_up", "standby": "unknown"}[mode],
                    "capacity_utilization_pct": 100 * abs(f) / limit if limit else None})
    return out


def _line_states_and_loads(model, pose):
    water = model.env.water_level_mllw_ft
    lines, ship_acc, pier_acc, wrench_f, moment = [], {}, {}, [0.0, 0.0], 0.0
    ship_cap = {f.fitting_id: f.swl_lbf for f in model.ship.fittings}
    ship_fit = {f.fitting_id: f for f in model.ship.fittings}
    unsupported_routing = set()
    pier_cap = {f.fitting_id: f.capacity_nominal_lbf for f in model.berth.fittings}
    for rec, st, tension in model.system.line_tensions(pose):
        ln = rec.ln
        bitt = ship_fit[ln.ship_fitting_id]
        chock_id = ln.chock_id or bitt.paired_chock_id
        lead = ship_fit.get(chock_id, bitt) if chock_id else bitt
        routed = lead.fitting_id != bitt.fitting_id
        ship_end = _pos(*model.system.frame.to_berth(bitt.x_ft, bitt.y_ft, pose), water + bitt.z_ft)
        lead_end = _pos(st.lead_berth[0], st.lead_berth[1], water + rec.lead_height_ft)
        pier_end = _pos(*rec.pier_xyz)
        # No working-limit field exists on the line model; "overloaded" is therefore never claimed.
        lines.append({**_live(f"line-{ln.line_number}"), "line_number": ln.line_number, "tension_lbf": tension,
                      "status": "slack" if tension == 0 else "taut", "ship_fitting_id": ln.ship_fitting_id,
                      "chock_id": lead.fitting_id if routed else None,
                      "pier_fitting_id": ln.pier_fitting_id, "ship_end": ship_end, "pier_end": pier_end,
                      "polyline": [ship_end, lead_end, pier_end] if routed else [ship_end, pier_end]})
        vec = (tension * st.ux, tension * st.uy, tension * st.uz)   # line pull on the ship fitting, toward the pier
        accumulators = [(pier_acc, ln.pier_fitting_id, -1.0)]
        if routed:
            # The integrator applies the external lead-to-pier wrench. It does not solve the inner segment's
            # tension/friction or the resultant reaction at a redirecting chock; do not label that wrench a
            # bitt/chock reaction. Geometry is still the catalog-supported bitt -> chock -> pier route.
            unsupported_routing.update((bitt.fitting_id, lead.fitting_id))
        else:
            accumulators.append((ship_acc, ln.ship_fitting_id, 1.0))
        for acc, fid, sign in accumulators:
            v = acc.setdefault(fid, [0.0, 0.0, 0.0])
            for i in range(3):
                v[i] += sign * vec[i]
        w = force_wrench(model.system.frame, pose, rec.lead_xy, vec[0], vec[1])
        wrench_f[0] += w.fx_lbf
        wrench_f[1] += w.fy_lbf
        moment += w.mz_ftlbf
    # Every configured line is reported. Inactive lines carry configuration (fitting IDs) only: IDs are not
    # measurement_fields, so they validate alongside availability "unavailable" and no tension/geometry.
    active = {ls["line_number"] for ls in lines}
    for n, rec in model.all_lines.items():
        if n in active:
            continue
        last = next((t.kind for t in reversed(model.transitions)
                     if t.element_id == f"line-{n}" and t.kind in ("secured", "tensioned", "released")), None)
        what = ("Line was released; no tension or geometry is reported."
                if last == "released" else "Line is not yet made fast; no tension or geometry is reported.")
        lines.append({"availability": "unavailable",
                      "validity": {"state": "unknown", "reasons": [{"code": "LINE_NOT_ACTIVE", "message": what,
                                   "affected_components": [f"line-{n}"]}]},
                      "provenance": {"kind": "unknown", "source": SOURCE, "references": [], "notes": []},
                      "line_number": n, "tension_lbf": None, "status": "unknown",
                      "ship_fitting_id": rec.ln.ship_fitting_id, "pier_fitting_id": rec.ln.pier_fitting_id,
                      "ship_end": None, "pier_end": None, "polyline": None})
    lines.sort(key=lambda d: d["line_number"])
    loads = []
    for owner, acc, cap in (("pier", pier_acc, pier_cap), ("ship", ship_acc, ship_cap)):
        for fid, v in acc.items():
            if owner == "ship" and fid in unsupported_routing:
                continue  # A known partial sum is not the total load on a fitting with an unmodeled lead.
            load, capacity = math.sqrt(sum(c * c for c in v)), cap.get(fid)
            loads.append({**_live(f"{owner}-{fid}"), "fitting_id": fid, "owner": owner, "load_lbf": load,
                          "capacity_lbf": capacity, "utilization_pct": 100 * load / capacity if capacity else None,
                          "force": _force(*v), "status": None})
    for fid in sorted(unsupported_routing):
        loads.append({"availability": "unavailable", "fitting_id": fid, "owner": "ship",
                      "validity": {"state": "unknown", "reasons": [{"code": "ROUTING_REACTION_UNMODELED",
                          "message": "Bitt/chock routing reactions are not resolved by the external line-segment model.",
                          "affected_components": [fid]}]},
                      "provenance": {"kind": "unknown", "source": SOURCE, "references": [], "notes": []},
                      "load_lbf": None, "capacity_lbf": None, "utilization_pct": None, "force": None, "status": None})
    return lines, loads, (wrench_f[0], wrench_f[1], moment)


def _wrench(component: str, fx: float, fy: float, mz: float) -> dict:
    return {**_live(component), "force": _force(fx, fy), "yaw_moment_ftlbf": mz}


def rich_frame(model, *, session_id: str, run_id: str, sequence: int, scene: SimScene,
               state=None, t: float | None = None, alerts: list[str] | None = None) -> SimFrame:
    """Legacy frame (model.frame) plus every rm0-v1 field, at `state`/`t` (defaults: current)."""
    legacy = model.frame(state, t, alerts)
    s = state or model.integrator.state
    t = legacy.t_s
    pose, frame, env, system = model.body.pose(s), model.system.frame, model.env, model.system

    # _deriv returns body-frame rates (du/dt, dv/dt, dr/dt). Berth-frame velocity is R(psi)*(u, v) with
    # R' = r*R*J, J(u, v) = (-v, u), so inertial acceleration of the ship origin in ship axes is
    #   a = nu_dot + r*J*nu  ->  a_surge = du/dt - v*r,  a_sway = dv/dt + u*r;  yaw accel = dr/dt.
    du, dv, dr = _deriv(model.params, s, model.forces(t, s))[3:]
    accel = (du - s[4] * s[5], dv + s[3] * s[5], dr)
    # S3: heave is prescribed from the S2 forcing water level only when a tide series is present; else unavailable.
    tide = model.forcing_env.water_level_mllw_ft if (
        model.forcing is not None and "water_level_mllw_ft" in model.forcing.supplied
        and model.forcing_env is not None) else None
    vert = vertical_state(tide, t_s=t)
    motion = {**_live("ship"),
        "pose": {"x_ft": s[0], "y_ft": s[1], "yaw_deg": math.degrees(s[2]), "heave_mllw_ft": vert.heave_mllw_ft},
        "velocity": {"surge_fps": s[3], "sway_fps": s[4], "yaw_degps": math.degrees(s[5])},
        "acceleration": {"surge_fps2": accel[0], "sway_fps2": accel[1], "yaw_degps2": math.degrees(accel[2])},
        "dofs": {"surge": "simulated", "sway": "simulated", "yaw": "simulated",
                 "heave": vert.heave_dof, "roll": vert.roll_dof, "pitch": vert.pitch_dof}}

    meta = env.metadata
    environment = {
        "t_s": t, "valid_at_utc": None,
        "wind": {**_live("wind"), "speed_kt": env.wind_speed_kt, "gust_kt": env.wind_gust_kt,
                 "from_true_deg": env.wind_from_true_deg, "metadata": meta},
        "current": {**_live("current"), "speed_kt": env.current_speed_kt, "set_true_deg": env.current_set_true_deg,
                    "metadata": meta},
        "water": {**_live("water"), "level_mllw_ft": env.water_level_mllw_ft, "metadata": meta},
        "waves": {name: _wave(name, "wave") for name in WAVE_NAMES},
    }

    if model.forcing is not None and model.forcing_env is not None:
        # S2: the frame must report the forcing the physics used at t, not the frozen base environment.
        fe, sup = model.forcing_env, model.forcing.supplied
        if all(n in sup for n in ("wind_speed_kt", "wind_gust_kt", "wind_from_true_deg")):
            environment["wind"].update(speed_kt=fe.wind_speed_kt, gust_kt=fe.wind_gust_kt, from_true_deg=fe.wind_from_true_deg)
        if all(n in sup for n in ("current_speed_kt", "current_set_true_deg")):
            environment["current"].update(speed_kt=fe.current_speed_kt, set_true_deg=fe.current_set_true_deg)
        if "water_level_mllw_ft" in sup:
            environment["water"].update(level_mllw_ft=fe.water_level_mllw_ft)

    line_states, fitting_loads, line_w = _line_states_and_loads(model, pose)

    status = {f.fender_id: f.status for f in legacy.fenders}
    fender_states, fender_w = [], [0.0, 0.0, 0.0]
    for fr, d, y in system.fender_loads(pose):
        fid, reaction = fr.model.fender_id, fr.model.force(d)
        fender_states.append({**_live(fid), "fender_id": fid, "compression_ft": d, "reaction_lbf": reaction,
                              "force": _force(0.0, reaction), "status": status[fid]})
        if d > 0:
            w = force_wrench_at(frame, pose, (fr.model.x_ft, y), 0.0, reaction)
            fender_w = [fender_w[0] + w.fx_lbf, fender_w[1] + w.fy_lbf, fender_w[2] + w.mz_ftlbf]

    loads = system.loads_at(pose)
    wind = (*frame.vector_to_berth(loads.wind.fx_lbf, loads.wind.fy_lbf, pose), loads.wind.mz_ftlbf)
    current = (*frame.vector_to_berth(loads.current.fx_lbf, loads.current.fy_lbf, pose), loads.current.mz_ftlbf)
    _, tug_fy, tug_mz = model.tug_wrench(t)
    tugs = (*frame.vector_to_berth(0.0, tug_fy, pose), tug_mz)
    forces = {
        "wind": _wrench("wind", *wind), "current": _wrench("current", *current),
        "waves": {name: {**_wave(name, "force"), "force": None, "yaw_moment_ftlbf": None} for name in WAVE_NAMES},
        "tugs": _wrench("tugs", *tugs), "lines": _wrench("lines", *line_w), "fenders": _wrench("fenders", *fender_w),
    }

    structured = [{"code": "SIMULATION_ALERT", "severity": "AMBER", "message": a, "element_ids": []}
                  for a in legacy.alerts if a.strip()]
    structured.append({"code": "SYNTHETIC_DYNAMICS", "severity": "INFO", "element_ids": [],
                       "message": "Synthetic unqualified demonstration dynamics on seed reference data; "
                                  "not a predictive vessel simulation."})
    provenance = {"kind": "estimated", "source": SOURCE, "references": [], "notes": [
        "Real RK4 integration of a synthetic, unqualified body (arbitrary mass, inertia and damping) with seed catalog data.",
        "Forces are berth-axes planar wrenches about the instantaneous ship origin; vertical components are not modeled.",
        "Acceleration is the inertial acceleration of the ship origin in ship axes (ft/s2, deg/s2): body-frame rates from the equations of motion with the rotation terms (-v*r surge, +u*r sway) added back.",
        "Tug position, velocity and acceleration are not modeled; tug forces follow the commanded linear slew.",
        "Waves and wakes are unavailable, not zero."]}

    return SimFrame.model_validate({
        **legacy.model_dump(), "schema_version": SCHEMA_VERSION, "sequence": sequence, "session_id": session_id,
        "run_id": run_id, "scene_id": scene.scene_id, "scene_revision": scene.revision,
        "motion": motion, "tug_states": _tug_states(model, s, t, pose), "environment": environment,
        "line_states": line_states, "fitting_loads": fitting_loads, "fender_states": fender_states,
        "forces": forces, "validity": legacy.validity.model_dump(), "provenance": provenance,
        "structured_alerts": structured})
