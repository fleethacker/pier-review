"""Motion authoring adapter; catalog references are never mutated by a training run."""
import math

from mooring import environment, refdata
from mooring.core.envelopes import new_id, resolved_inputs_hash, utcnow
from mooring.core.schemas import Scenario, ShipState, Validity, ValidityReason
from mooring.core.schemas.motion_controls import LocalDepthPatch
from mooring.core.schemas.motion_workspace import (
    MotionWorkspaceCatalog, MotionWorkspacePreset, MotionWorkspaceScenario, MotionWorkspaceSpec,
)
from mooring.core.store import DocStore
from mooring.data_simulation.motion_scenarios import (
    DEMO_SHIPS, NORFOLK_BERTH, TRAINING_TUG_BOW_CLEARANCE_FT, norfolk_route, ship_for_training, training_environment,
)
from mooring.data_simulation.shoreline import NORFOLK_BERTHS, validate_initial
from mooring.templates import template_config
from mooring.transit.geo import LocalPlane, bearing_deg

SCENARIOS = DocStore("motion_workspace_scenarios", MotionWorkspaceScenario)


def workspace_validity() -> Validity:
    return Validity(state="limited", reasons=[
        ValidityReason(code="MOTION_TRAINING_CONFIGURATION",
            message="Training configuration with unqualified propulsion, hydrodynamics, stability and reference assets."),
        ValidityReason(code="MOTION_NOT_NAVIGATIONAL_GUIDANCE",
            message="Demonstrator only: no pilot approval, complete hazard coverage or engineering qualification."),
        ValidityReason(code="MOTION_SHORELINE_PARTIAL",
            message="Initial footprints checked against a bounded NOAA shoreline fixture only; missing geography is unknown and runtime shoreline collision is not modeled."),
    ])


def training_controls(ship, loading, berth):
    from .loading import synthetic_motion_controls
    controls = synthetic_motion_controls(ship, loading)
    controls.loading.local_depth = LocalDepthPatch(
        basis="synthetic", source="Notional berth catalog depth, constant training patch; not a seabed survey",
        depth_mllw_ft=min(point.depth_mllw_ft for point in berth.depth_profile), uncertainty_ft=None,
        x_min_ft=0, x_max_ft=berth.face_length_ft, y_min_ft=0, y_max_ft=600,
    )
    return controls


def resolve_tug_controls(spec, ship, berth):
    """Materialize each authored tug body in the saved immutable configuration."""
    from .tug_dynamics import synthetic_tug_dynamics_config
    points = sorted((p for p in ship.push_points if p.side != spec.side_to), key=lambda p: -p.x_ft)
    if spec.tug_ids is None:
        spec.tug_ids = [t.tug_id for t in refdata.tugs()[:len(points)]]
    supplied = {c.tug_id: c for c in spec.controls.tug_dynamics}
    if set(supplied) - set(spec.tug_ids):
        raise ValueError("A dynamic tug configuration must belong to the selected fleet")
    initial = initial_state(spec, ship, berth)
    spec.controls.tug_dynamics = [supplied.get(tid) or synthetic_tug_dynamics_config(
        refdata.tug(tid), ship, point, initial, berth.face_bearing_true_deg,
        bow_gap_ft=TRAINING_TUG_BOW_CLEARANCE_FT)
        for tid, point in zip(spec.tug_ids, points)]


def catalog() -> MotionWorkspaceCatalog:
    berth = refdata.berth(NORFOLK_BERTH)
    ships = [refdata.ship(class_id) for class_id in DEMO_SHIPS]
    route = norfolk_route(berth)
    descriptions = (
        ("DDG controlled berthing", "Start paused near the pier; try helm, tugs and line handling.", "berth"),
        ("Cruiser approach", "Bring the cruiser alongside with explicit tug and engine orders.", "approach"),
        ("Amphibious loading exercise", "Compare payload placement, trim, heel and local under-keel clearance.", "berth"),
        ("Carrier channel arrival", "Follow the documented demonstration water route to the pier approach, then berth manually.", "channel"),
    )
    presets = []
    for ship, (title, description, start) in zip(ships, descriptions):
        config = MotionWorkspaceSpec(name=title, ship_class_id=ship.class_id, start=start,
            controls=training_controls(ship, "full_load", berth),
            environment=training_environment(utcnow()),
            tug_ids=[] if start == "channel" else [t.tug_id for t in refdata.tugs()[:2]],
            duration_s=14400 if start == "channel" else 3600,
            route_id=route.route_id if start == "channel" else None, route_follow=start == "channel")
        presets.append(MotionWorkspacePreset(preset_id=f"motion-{ship.class_id.lower()}", title=title,
            description=description, configuration=config, validity=workspace_validity()))
    return MotionWorkspaceCatalog(ships=ships, berths=[b for b in refdata.berths() if b.berth_id.startswith("NAVSTA-NORFOLK")],
        tugs=refdata.tugs(), presets=presets, routes=[route])


def resolve_configuration(spec: MotionWorkspaceSpec) -> MotionWorkspaceSpec:
    """Resolve explicit training defaults without a saved scenario or session."""
    ship, berth = refdata.ship(spec.ship_class_id), refdata.berth(spec.berth_id)
    ship_for_training(ship, spec.loading)  # validates loading without mutating the catalog
    if berth.berth_id not in NORFOLK_BERTHS:
        raise ValueError("Motion workspace geographic demo coverage is Norfolk only")
    if spec.route_id and (spec.route_id != norfolk_route(berth).route_id or berth.berth_id != NORFOLK_BERTH):
        raise ValueError("The selected demonstration route is bound to Norfolk Pier 12 North")
    if spec.start == "channel" and not spec.route_id:
        raise ValueError("Channel start requires a selected route")
    if spec.tug_ids is not None:
        for tid in spec.tug_ids:
            refdata.tug(tid)
        if len(spec.tug_ids) > sum(p.side != spec.side_to for p in ship.push_points):
            raise ValueError("More selected tugs than distinct water-side hull push points")
    spec = spec.model_copy(deep=True)
    if spec.controls is None:
        spec.controls = training_controls(ship, spec.loading, berth)
    resolve_tug_controls(spec, ship, berth)
    validate_initial(berth, ship, initial_state(spec, ship, berth), spec.controls.tug_dynamics)
    if spec.environment_mode == "synthetic":
        spec.environment = training_environment(utcnow(), spec.environment)
    return spec


def create_scenario(spec: MotionWorkspaceSpec) -> MotionWorkspaceScenario:
    spec = resolve_configuration(spec)
    row = MotionWorkspaceScenario(motion_scenario_id=new_id("motion"), created_at_utc=utcnow(),
        revision=resolved_inputs_hash(spec), configuration=spec, validity=workspace_validity())
    SCENARIOS[row.motion_scenario_id] = row
    return row


def get_scenario(scenario_id: str) -> MotionWorkspaceScenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError:
        raise refdata.NotFound("Motion scenario not found") from None


def resolve_environment(spec: MotionWorkspaceSpec):
    if spec.environment_mode == "live":
        return environment.live_snapshot(spec.berth_id)
    if spec.environment_mode == "synthetic":
        return training_environment(utcnow(), spec.environment)
    return spec.environment.model_copy(deep=True)


def initial_state(spec, ship, berth):
    if spec.initial_state is not None:
        return spec.initial_state.model_copy(deep=True)
    heading = (berth.face_bearing_true_deg + (180 if spec.side_to == "port" else 0)) % 360
    x = berth.face_length_ft / 2
    if spec.start == "channel":
        route = norfolk_route(berth)
        start, next_point = route.waypoints[:2]
        plane = LocalPlane(berth.origin_lat, berth.origin_lon)
        east, north = plane.to_local(start.lat, start.lon)
        b = math.radians(berth.face_bearing_true_deg)
        x = (east * math.sin(b) + north * math.cos(b)) / 0.3048
        y = (east * math.sin(b-math.pi/2) + north * math.cos(b-math.pi/2)) / 0.3048
        e2, n2 = plane.to_local(next_point.lat, next_point.lon)
        heading = bearing_deg(e2-east, n2-north)
    else:
        # Authored holding station in each face's basin, checked with complete
        # ship/tug envelopes for all classes/sides. The old North-face y=900
        # station lies on NOAA's Pier 14 land polygon. This is not a safe-water
        # claim or a maneuvering minimum; external coverage remains incomplete.
        y = 300.0 if spec.start == "approach" else ship.beam_ft / 2 + max((f.standoff_ft for f in berth.fenders), default=0) + 10
    return ShipState(x_ft=x, y_ft=y, heading_true_deg=heading)


def build_model(row):
    from .simulator import BerthingModel
    from mooring.core.schemas.motion_controls import SimLineControlMessage
    spec = row.configuration
    ship = ship_for_training(refdata.ship(spec.ship_class_id), spec.loading)
    berth = refdata.berth(spec.berth_id)
    initial = initial_state(spec, ship, berth)
    # Recheck persisted rows as well as authoring requests: old saved poses or
    # supplied tug bodies must not bypass the current geography guard.
    validate_initial(berth, ship, initial, spec.controls.tug_dynamics if spec.controls else [])
    line_spec = ship.standard_line_outfit[0].spec_id if ship.standard_line_outfit else "NYLON-DB-7IN"
    config = template_config(ship, berth, spec.side_to, berth.face_length_ft/2, line_spec)
    # This private Scenario is not added to the static-planning catalog: its notional
    # session-only fittings must never be mistaken for class reference data.
    sc = Scenario(scenario_id=row.motion_scenario_id, created_at_utc=row.created_at_utc,
        name=spec.name, ship_class_id=ship.class_id, loading=spec.loading, berth_id=berth.berth_id,
        side_to=spec.side_to, env_source={"mode": "mock"}, config=config)
    env = resolve_environment(spec)
    guidance = None
    if spec.route_follow:
        from .route_guidance import RouteGuidance, RoutePoint
        from mooring.core.units import KT_TO_FPS
        plane = LocalPlane(berth.origin_lat, berth.origin_lon)
        angle = math.radians(berth.face_bearing_true_deg)
        points = []
        for w in norfolk_route(berth).waypoints:
            east, north = plane.to_local(w.lat, w.lon)
            points.append(RoutePoint((east*math.sin(angle)+north*math.cos(angle))/.3048,
                (east*math.sin(angle-math.pi/2)+north*math.cos(angle-math.pi/2))/.3048,
                w.speed_kt*KT_TO_FPS, w.name))
        guidance = RouteGuidance(points, spec.route_id, vessel_length_ft=ship.loa_ft)
    model = BerthingModel(sc, initial, env, dt=spec.dt_s, duration=spec.duration_s, forcing=spec.forcing,
        controls=spec.controls, ship_override=ship, tug_ids=spec.tug_ids, guidance=guidance)
    model.motion_geography = True
    if spec.initial_lines_attached:
        for number, rec in model.all_lines.items():
            length = model.system.line_state(rec, model.body.pose(model.integrator.state)).length_ft
            model.schedule(SimLineControlMessage(type="line_control", line_number=number,
                attached=True, paid_out_length_ft=length))
        model.apply_pending()
    return model
