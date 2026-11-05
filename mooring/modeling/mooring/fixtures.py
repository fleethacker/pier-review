"""Synthetic analytical fixtures for mechanics and solver tests.

A rectangular synthetic hull, a straight pier and a perfectly linear line, with simple round numbers so expected values
can be computed by hand. Provenance is `synthetic`: these are NOT any real ship, pier or rope, and are not in the
catalog the API serves. The labeled DDG demonstration remains the seed catalog.
"""

from datetime import UTC, datetime

from mooring.core.schemas import (
    Berth, EnvironmentSnapshot, Fender, LineSpec, LoadingCondition, MooringConfig, MooringLine, PierFitting, Provenance,
    PushPoint, ShipClass, ShipFitting, TugAssignment,
)

SYNTH = Provenance(source="SYNTHETIC ANALYTICAL FIXTURE", confidence="synthetic", notes="Round numbers for hand-checkable tests; not real data.")
LINEAR_SPEC_ID = "SYN-LINEAR"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def synthetic_line_spec(mbs_lbf: float = 100_000.0, strain_at_mbs: float = 0.4, wet_factor: float = 1.0) -> LineSpec:
    return LineSpec(spec_id=LINEAR_SPEC_ID, material="polyester", construction="double_braid", size_circ_in=8, mbs_lbf=mbs_lbf,
                    load_elongation=[(0.0, 0.0), (1.0, strain_at_mbs)], wet_strength_factor=wet_factor, provenance=SYNTH)


def synthetic_ship() -> ShipClass:
    fittings = []
    for n, x in enumerate((150.0, 50.0, -50.0, -150.0), start=1):
        for side, y in (("port", 28.0), ("starboard", -28.0)):
            s = "P" if side == "port" else "S"
            fittings.append(ShipFitting(fitting_id=f"BITT-{n}{s}", kind="bitt", x_ft=x, y_ft=y, z_ft=20.0, side=side, swl_lbf=500_000.0,
                                        paired_chock_id=f"CHOCK-{n}{s}"))
            fittings.append(ShipFitting(fitting_id=f"CHOCK-{n}{s}", kind="chock", x_ft=x, y_ft=y * 30 / 28, z_ft=20.0, side=side))
    return ShipClass(
        class_id="SYN-BOX", name="Synthetic box hull", hull_type="DDG", loa_ft=400.0, lwl_ft=400.0, beam_ft=60.0, block_coefficient=0.6,
        loading_conditions=[LoadingCondition(name="full_load", displacement_lt=10_000, draft_fwd_ft=20, draft_aft_ft=20, freeboard_ft=20)],
        wind_area_lateral_ft2=10_000, wind_area_frontal_ft2=2_000, hull_wind_area_lateral_ft2=4_000, wind_drag_class="typical",
        fittings=fittings,
        push_points=[PushPoint(push_point_id="PP-FWD-P", x_ft=120.0, side="port", max_force_lbf=1e9),
                     PushPoint(push_point_id="PP-AFT-P", x_ft=-120.0, side="port", max_force_lbf=1e9),
                     PushPoint(push_point_id="PP-FWD-S", x_ft=120.0, side="starboard", max_force_lbf=1e9)],
        mst_class="II", provenance=SYNTH)


def synthetic_berth(fender_stiffness: float = 100_000.0, fender_energy: float = 1_000_000.0) -> Berth:
    from mooring.core.schemas import DepthPoint, EnvStations
    fittings = [PierFitting(fitting_id=f"B{x:03d}", kind="bollard_special_b", x_ft=float(x), y_ft=-6.0, capacity_nominal_lbf=500_000.0)
                for x in range(100, 701, 50)]
    return Berth(berth_id="SYN-PIER", name="Synthetic pier", face_bearing_true_deg=90.0, origin_lat=36.9, origin_lon=-76.3,
                 face_length_ft=800.0, deck_height_mllw_ft=8.0, depth_profile=[DepthPoint(x_ft=0, depth_mllw_ft=40), DepthPoint(x_ft=800, depth_mllw_ft=40)],
                 fittings=fittings, fenders=[Fender(fender_id=f"F{x}", kind="camel", x_ft=float(x), length_ft=40.0, standoff_ft=10.0,
                                                    stiffness_lbf_per_ft=fender_stiffness, rated_energy_ftlbf=fender_energy) for x in (300, 400, 500)],
                 env_station_ids={"wind": "w", "current": "c", "water_level": "l"}, provenance=SYNTH)


def calm_env(water_level: float = 0.0) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(valid_at_utc=T0, source="scenario", wind_speed_kt=0, wind_gust_kt=0, wind_from_true_deg=0,
                               current_speed_kt=0, current_set_true_deg=0, water_level_mllw_ft=water_level)


def breast_config(side_to: str = "starboard", ship_x: float = 400.0, pretension: float | None = 0.0, parts: int = 1,
                  pairs: tuple[int, ...] = (1, 4), springs: bool = False, standoff: float = 10.0) -> MooringConfig:
    """Perpendicular breast lines from bitts at the given numbers to the bollard abeam (y = -6)."""
    s = "S" if side_to == "starboard" else "P"
    x_of = {1: 150.0, 2: 50.0, 3: -50.0, 4: -150.0}
    sign = 1 if side_to == "starboard" else -1
    lines = []
    for i, n in enumerate(pairs, start=1):
        px = ship_x + sign * (x_of[n] * 30 / 28 * 0 + x_of[n])  # bollard abeam the chock
        px = round((ship_x + sign * x_of[n]) / 50) * 50
        lines.append(MooringLine(line_number=i, spec_id=LINEAR_SPEC_ID, parts=parts, ship_fitting_id=f"BITT-{n}{s}",
                                 pier_fitting_id=f"B{int(px):03d}", pretension_lbf=pretension))
    if springs:  # a forward bitt leading aft and an aft bitt leading forward give surge restraint
        for n, off in ((1, -100.0), (4, 100.0)):
            px = round((ship_x + sign * (x_of[n] + off)) / 50) * 50
            lines.append(MooringLine(line_number=len(lines) + 1, spec_id=LINEAR_SPEC_ID, parts=parts, ship_fitting_id=f"BITT-{n}{s}",
                                     pier_fitting_id=f"B{int(px):03d}", pretension_lbf=pretension))
    return MooringConfig(side_to=side_to, ship_x_ft=ship_x, standoff_ft=standoff, lines=lines)


def tug(point: str, force: float, mode: str = "push", direction_true_deg: float | None = None) -> TugAssignment:
    return TugAssignment(tug_id="T-SYN", push_point_id=point, mode=mode, force_lbf=force, direction_true_deg=direction_true_deg)
