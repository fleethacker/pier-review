"""Ship/berth frame transforms and mooring line geometry. Real (not mock): shared by every module.

Frames are defined in mooring/core/schemas/refdata.py. Starboard side to puts the bow toward berth +x;
port side to puts the bow toward berth -x.
"""

import math
from dataclasses import dataclass

from .schemas import Berth, MooringConfig, MooringLine, PierFitting, ShipClass, ShipFitting

PIER_FITTING_HEIGHT_FT = 1.5  # line attachment height above the pier deck
DEFAULT_STANDOFF_FT = 12.0


def ship_heading_true(berth: Berth, side_to: str) -> float:
    """True heading of the ship's bow when moored to this berth."""
    if side_to == "starboard":
        return berth.face_bearing_true_deg % 360
    return (berth.face_bearing_true_deg + 180) % 360


def standoff_ft(berth: Berth, config: MooringConfig) -> float:
    if config.standoff_ft is not None:
        return config.standoff_ft
    if berth.fenders:
        return max(f.standoff_ft for f in berth.fenders)
    return DEFAULT_STANDOFF_FT


def ship_to_berth(xs: float, ys: float, ship: ShipClass, berth: Berth, config: MooringConfig) -> tuple[float, float]:
    """Ship-frame (x, y) -> berth-frame (x, y) for a ship lying parallel to the face."""
    yc = standoff_ft(berth, config) + ship.beam_ft / 2
    if config.side_to == "starboard":
        return config.ship_x_ft + xs, yc + ys
    return config.ship_x_ft - xs, yc - ys


def depth_at(berth: Berth, x_ft: float) -> float:
    """Linear interpolation of the berth depth profile (MLLW)."""
    pts = sorted(berth.depth_profile, key=lambda p: p.x_ft)
    if x_ft <= pts[0].x_ft:
        return pts[0].depth_mllw_ft
    for a, b in zip(pts, pts[1:]):
        if x_ft <= b.x_ft:
            t = (x_ft - a.x_ft) / (b.x_ft - a.x_ft) if b.x_ft != a.x_ft else 0
            return a.depth_mllw_ft + t * (b.depth_mllw_ft - a.depth_mllw_ft)
    return pts[-1].depth_mllw_ft


@dataclass
class LineGeometry:
    line: MooringLine
    ship_fitting: ShipFitting
    lead_point: ShipFitting  # chock if any, else the bitt
    pier_fitting: PierFitting
    length_ft: float
    horiz_length_ft: float
    horiz_angle_deg: float  # from perpendicular to the ship
    vert_angle_deg: float
    leads_forward: bool  # pier fitting is forward of the lead point along the ship
    role: str

    @property
    def breast_efficiency(self) -> float:
        return math.cos(math.radians(self.horiz_angle_deg))

    @property
    def lateral_factor(self) -> float:
        """Share of tension acting perpendicular to the pier."""
        return math.cos(math.radians(self.horiz_angle_deg)) * math.cos(math.radians(self.vert_angle_deg))

    @property
    def longitudinal_factor(self) -> float:
        return math.sin(math.radians(self.horiz_angle_deg)) * math.cos(math.radians(self.vert_angle_deg))


def classify_role(ship: ShipClass, lead_x_ft: float, horiz_angle_deg: float, leads_forward: bool) -> str:
    """Name a line from its lead (NSTM 582-4.2.2): breast lines are under 45 deg from perpendicular."""
    end_zone = 0.35 * ship.loa_ft
    if horiz_angle_deg < 45:
        return "breast"
    if lead_x_ft > end_zone and leads_forward:
        return "bow"
    if lead_x_ft < -end_zone and not leads_forward:
        return "stern"
    return "spring_fwd" if leads_forward else "spring_aft"


def line_geometry(
    line: MooringLine,
    ship: ShipClass,
    berth: Berth,
    config: MooringConfig,
    water_level_mllw_ft: float,
) -> LineGeometry:
    fittings = {f.fitting_id: f for f in ship.fittings}
    pier = {f.fitting_id: f for f in berth.fittings}
    if line.ship_fitting_id not in fittings:
        raise KeyError(f"Ship fitting '{line.ship_fitting_id}' not found on {ship.class_id}")
    if line.pier_fitting_id not in pier:
        raise KeyError(f"Pier fitting '{line.pier_fitting_id}' not found on {berth.berth_id}")
    bitt = fittings[line.ship_fitting_id]
    chock_id = line.chock_id or bitt.paired_chock_id
    lead = fittings.get(chock_id, bitt) if chock_id else bitt
    pf = pier[line.pier_fitting_id]

    lx, ly = ship_to_berth(lead.x_ft, lead.y_ft, ship, berth, config)
    lz = water_level_mllw_ft + lead.z_ft
    pz = berth.deck_height_mllw_ft + PIER_FITTING_HEIGHT_FT
    dx, dy, dz = pf.x_ft - lx, pf.y_ft - ly, pz - lz
    horiz = math.hypot(dx, dy)
    length = math.sqrt(horiz**2 + dz**2)
    horiz_angle = math.degrees(math.atan2(abs(dx), abs(dy)))
    vert_angle = math.degrees(math.atan2(abs(dz), horiz)) if horiz > 0 else 90.0
    leads_forward = dx > 0 if config.side_to == "starboard" else dx < 0
    role = line.role or classify_role(ship, lead.x_ft, horiz_angle, leads_forward)
    return LineGeometry(
        line=line,
        ship_fitting=bitt,
        lead_point=lead,
        pier_fitting=pf,
        length_ft=length,
        horiz_length_ft=horiz,
        horiz_angle_deg=horiz_angle,
        vert_angle_deg=vert_angle,
        leads_forward=leads_forward,
        role=role,
    )


def strain_at(load_fraction: float, curve: list[tuple[float, float]]) -> float:
    """Interpolate a [fraction of MBS, strain] stretch curve."""
    pts = sorted(curve)
    if load_fraction <= pts[0][0]:
        return pts[0][1]
    for (f0, s0), (f1, s1) in zip(pts, pts[1:]):
        if load_fraction <= f1:
            return s0 + (load_fraction - f0) / (f1 - f0) * (s1 - s0)
    (f0, s0), (f1, s1) = pts[-2], pts[-1]
    return s1 + (load_fraction - f1) / (f1 - f0) * (s1 - s0)
