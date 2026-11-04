"""Static environmental loads, UFC 4-159-03 Chapter 4 (2020).

Component functions use feet, seconds, slugs, and UFC flow-TOWARD angles measured
counterclockwise from +x. ``compute_loads`` converts the public clockwise wind-FROM /
current-TOWARD bearings. This distinction also explains the stern coefficient in
UFC's 40-degree longitudinal wind example. Pure functions do not read seed data.
"""

import math

from mooring.core.schemas import ForceComponent, ForceSet, LoadsResult
from mooring.core.units import G_FPS2, KGM3_TO_SLUG_FT3, KT_TO_FPS, LT_TO_LB
from mooring import refdata
from . import coefficients as c


def fold_angle(angle):
    """UFC Eqs. 4-5/4-6, pp. 63–64; symmetric angle in [0, 180]."""
    angle %= 360
    return min(angle, 360 - angle)


def transverse_wind_coefficient(area, hull_area, lwl, superstructure_height, drag_class):
    """UFC Eq. 4-2, p. 55; superstructure height is above the waterline."""
    if not 0 < hull_area <= area or lwl <= 0 or superstructure_height <= 0:
        raise ValueError("Wind areas, waterline length and height must be positive; hull area <= total area.")
    hh = hull_area / lwl
    return c.WIND_CLASS[drag_class] * (
        (0.5 * (superstructure_height + hh) / c.REFERENCE_HEIGHT_FT) ** c.HEIGHT_EXPONENT * (area - hull_area)
        + (0.5 * hh / c.REFERENCE_HEIGHT_FT) ** c.HEIGHT_EXPONENT * hull_area
    ) / area


def transverse_wind_shape(angle):
    """UFC Eq. 4-3, p. 55 / Figure 4-4; harmonic restored from 2016 Eq. (4)."""
    t = math.radians(angle)
    return (math.sin(t) - c.TRANSVERSE_WEIGHT * math.sin(c.TRANSVERSE_HARMONIC * t)) / c.TRANSVERSE_NORMALIZATION


def transverse_wind_force(rho, speed, area, coefficient, angle):
    """UFC Eq. 4-1, p. 54; returns lbf."""
    return 0.5 * rho * speed**2 * area * coefficient * transverse_wind_shape(angle)


def longitudinal_wind_shape(angle, crossing, distributed):
    """UFC Eqs. 4-5/4-6, pp. 63–64; corrected symmetric folding from 2005 text."""
    t = fold_angle(angle)
    phase = 90 * t / crossing if t <= crossing else 90 * (t - crossing) / (180 - crossing) + 90
    if not distributed:
        return math.cos(math.radians(phase))
    gamma = math.radians(phase + 90)
    return (math.sin(gamma) - c.LONGITUDINAL_WEIGHT * math.sin(c.LONGITUDINAL_HARMONIC * gamma)) / c.LONGITUDINAL_NORMALIZATION


def longitudinal_wind_force(rho, speed, area, angle, drag_class):
    """UFC Eq. 4-4, p. 62, Tables 4-3/4-4; flow toward bow uses stern coefficient."""
    crossing = c.WIND_CROSSING[drag_class]
    shape = longitudinal_wind_shape(angle, crossing, drag_class == "extensive_superstructure")
    bow, stern = c.WIND_LONGITUDINAL[drag_class]
    coefficient = stern if fold_angle(angle) <= crossing else bow
    return 0.5 * rho * speed**2 * area * coefficient * shape


def wind_yaw_coefficient(angle, kind):
    """UFC Eq. 4-8 / Table 4-5, pp. 65–66; mirrored for the opposite side."""
    zero, a1, a2 = c.WIND_YAW[kind]
    t = fold_angle(angle)
    value = -a1 * math.sin(math.radians(t * 180 / zero)) if t < zero else a2 * math.sin(math.radians((t - zero) * 180 / (180 - zero)))
    return value if angle % 360 <= 180 else -value


def wind_yaw_moment(rho, speed, area, length, angle, kind):
    """UFC Eq. 4-7, p. 65; returns ft·lbf about midships (CG assumed there)."""
    return 0.5 * rho * speed**2 * area * length * wind_yaw_coefficient(angle, kind)


def transverse_current_coefficient(lwl, beam, draft, volume, midship, depth):
    """UFC Eqs. 4-10–4-14, pp. 71–72 / Figure 4-9; T/d clamped to [0, 1]."""
    if min(lwl, beam, draft, volume, depth) <= 0 or not 0 < midship <= 1:
        raise ValueError("Current geometry/depth must be positive and 0 < midship coefficient <= 1.")
    chi = lwl**2 * (midship * beam * draft) / (beam * volume)
    deep = c.DEEP_CURRENT_FACTOR * math.sqrt(chi)
    ratio = min(draft / depth, c.MAX_DRAFT_DEPTH_RATIO)
    return deep + (c.SHALLOW_CURRENT_COEFFICIENT - deep) * ratio**c.CURRENT_DEPTH_EXPONENT


def transverse_current_force(rho, speed, lwl, draft, coefficient, angle):
    """UFC Eq. 4-9, p. 68; returns lbf."""
    return 0.5 * rho * speed**2 * lwl * draft * coefficient * math.sin(math.radians(angle))


def wetted_surface(lwl, draft, volume):
    """UFC Eq. 4-18, p. 75: displacement/weight density is submerged volume."""
    return c.WETTED_FACTOR * draft * lwl + volume / draft


def propeller_area(lwl, beam, hull_type):
    """UFC Eqs. 4-22/4-23, Table 4-7, p. 76; LHD uses carrier analogy."""
    return lwl * beam / c.PROPELLER_AREA_RATIO.get(hull_type, c.PROPELLER_AREA_RATIO["DDG"]) / c.PROPELLER_EXPANSION


def friction_coefficient(speed, lwl, angle):
    """UFC Eqs. 4-19/4-20, pp. 75–76; explicit numerical floor at low Reynolds number."""
    axial = abs(math.cos(math.radians(angle)))
    if speed == 0 or axial < c.AXIAL_COS_TOLERANCE:
        return 0.0, 0.0
    reynolds = abs(speed) * lwl * axial / c.WATER_VISCOSITY_FT2_S
    coefficient = c.FRICTION_FACTOR / (math.log10(max(reynolds, c.MIN_FRICTION_REYNOLDS)) - c.FRICTION_LOG_OFFSET)**2
    return coefficient, reynolds


def longitudinal_current_components(rho, speed, beam, draft, lwl, surface, propeller, angle):
    """UFC Eqs. 4-15–4-23, pp. 75–76: form, skin friction, propeller drag (lbf)."""
    cosine = math.cos(math.radians(angle))
    if abs(cosine) < c.AXIAL_COS_TOLERANCE:
        return 0.0, 0.0, 0.0
    friction, _ = friction_coefficient(speed, lwl, angle)
    q = 0.5 * rho * speed**2 * cosine
    return q * beam * draft * c.FORM_DRAG, q * surface * friction, q * propeller * c.PROPELLER_DRAG


def current_yaw_moment(force, lwl, angle, kind):
    """UFC Eqs. 4-24–4-26, Table 4-10, pp. 78–79; level-keel approximation."""
    a, b = c.CURRENT_YAW[kind]
    return force * (a + b * fold_angle(angle)) * lwl


def ship_inputs(ship, loading, water_density):
    """Resolve optional geometry with explicit estimates; no seed reads or mutations."""
    lc = next((item for item in ship.loading_conditions if item.name == loading), None)
    if lc is None:
        raise refdata.InvalidReference(f"Unknown loading {loading!r} for {ship.class_id}")
    draft = (lc.draft_fwd_ft + lc.draft_aft_ft) / 2
    volume = lc.displacement_lt * LT_TO_LB / (water_density * KGM3_TO_SLUG_FT3 * G_FPS2)
    height = getattr(ship, "superstructure_height_ft", None)
    if height is None:
        height = ship.hull_wind_area_lateral_ft2 / ship.lwl_ft + (ship.wind_area_lateral_ft2 - ship.hull_wind_area_lateral_ft2) / (c.SUPERSTRUCTURE_LENGTH_FRACTION * ship.lwl_ft)
    midship = getattr(ship, "midship_coefficient", None) or c.ESTIMATED_MIDSHIP_COEFFICIENT
    surface = getattr(ship, "wetted_surface_ft2", None)
    if surface is None or loading != "full_load":
        surface = wetted_surface(ship.lwl_ft, draft, volume)
    propeller = getattr(ship, "propeller_expanded_area_ft2", None)
    if propeller is None:
        propeller = propeller_area(ship.lwl_ft, ship.beam_ft, ship.hull_type)
    return draft, volume, height, midship, surface, propeller


def compute_loads(ship, loading, heading_true_deg, env, water_depth_ft, use_gust=True, shielding_factor=1.0) -> LoadsResult:
    """UFC Eqs. 4-1–4-26, pp. 54–79; public signature, Navy units and API bearings.

    Sustained input is converted from 60 s to 30 s using graphical Figure 3-5
    synoptic readings. Gust input is assumed already 30 s (duration absent in API).
    Shielding multiplies every wind force/moment, never current.
    """
    if not math.isfinite(water_depth_ft) or water_depth_ft <= 0:
        raise ValueError("Water depth must be positive and finite.")
    if not 0 <= shielding_factor <= 1:
        raise ValueError("Shielding factor must be between zero and one.")
    rho_a, rho_w = env.air_density_kgm3 * KGM3_TO_SLUG_FT3, env.water_density_kgm3 * KGM3_TO_SLUG_FT3
    vw = (env.wind_gust_kt if use_gust else env.wind_speed_kt * c.SUSTAINED_TO_30S) * KT_TO_FPS
    vc = env.current_speed_kt * KT_TO_FPS
    rel_w, rel_c = (env.wind_from_true_deg - heading_true_deg) % 360, (env.current_set_true_deg - heading_true_deg) % 360
    tw, tc = (180 - rel_w) % 360, (-rel_c) % 360
    draft, volume, height, midship, surface, propeller = ship_inputs(ship, loading, env.water_density_kgm3)
    cy = transverse_wind_coefficient(ship.wind_area_lateral_ft2, ship.hull_wind_area_lateral_ft2, ship.lwl_ft, height, ship.wind_drag_class)
    yaw_kind = "destroyer" if ship.hull_type in ("DDG", "CG") else "carrier" if ship.hull_type in ("CVN", "LHD") else "midships"
    longitudinal_class = "extensive_superstructure" if ship.hull_type in ("DDG", "CG") else ship.wind_drag_class
    wind = ForceComponent(
        fx_lbf=shielding_factor * longitudinal_wind_force(rho_a, vw, ship.wind_area_frontal_ft2, tw, longitudinal_class),
        fy_lbf=shielding_factor * transverse_wind_force(rho_a, vw, ship.wind_area_lateral_ft2, cy, tw),
        mz_ftlbf=shielding_factor * wind_yaw_moment(rho_a, vw, ship.wind_area_lateral_ft2, ship.loa_ft, tw, yaw_kind),
        coefficients={"cy": cy, "wind_speed_basis_factor": 1.0 if use_gust else c.SUSTAINED_TO_30S},
    )
    cyc = transverse_current_coefficient(ship.lwl_ft, ship.beam_ft, draft, volume, midship, water_depth_ft)
    fy = transverse_current_force(rho_w, vc, ship.lwl_ft, draft, cyc, tc)
    components = longitudinal_current_components(rho_w, vc, ship.beam_ft, draft, ship.lwl_ft, surface, propeller, tc)
    friction, reynolds = friction_coefficient(vc, ship.lwl_ft, tc)
    current = ForceComponent(
        fx_lbf=sum(components), fy_lbf=fy,
        mz_ftlbf=current_yaw_moment(fy, ship.lwl_ft, tc, "carrier" if yaw_kind == "carrier" else "warship"),
        coefficients={"cyc": cyc, "depth_draft_ratio": max(water_depth_ft / draft, 1.0),
                      "cxca": friction, "reynolds": reynolds},
    )
    total = ForceSet(fx_lbf=wind.fx_lbf + current.fx_lbf, fy_lbf=wind.fy_lbf + current.fy_lbf,
                     mz_ftlbf=wind.mz_ftlbf + current.mz_ftlbf)
    return LoadsResult(wind=wind, current=current, total=total, wind_rel_ship_deg=rel_w, current_rel_ship_deg=rel_c)
