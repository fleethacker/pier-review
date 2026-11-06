"""Authored Motion training inputs, isolated from reference and observation catalogs.

Fitting geometry is deliberately synthetic and never registered as real class data.
Route stations reuse the existing coastline-tested Norfolk transit demonstration,
not a pilot plan or a depth-qualified channel centerline.
"""
import math

from mooring.core.schemas import EnvironmentMetadata, EnvironmentSnapshot, ShipClass, ShipFitting
from mooring.core.schemas.motion_workspace import MotionRoute, MotionWaypoint
from mooring.transit.geo import LocalPlane

NORFOLK_BERTH = "NAVSTA-NORFOLK-P12-N"
DEMO_SHIPS = ("DDG-51-FIIA", "CG-47", "LHD-1", "CVN-68")
FITTING_STATIONS = (0.40, 0.25, 0.10, -0.10, -0.25, -0.40)  # authored fractions of LWL
SYNTHETIC_BITT_SWL_LBF = 200_000.0  # arbitrary training rating; not a ship fitting rating
TRAINING_TUG_BOW_CLEARANCE_FT = 45.0  # authored standby placement; not a maneuvering minimum


def ship_for_training(ship: ShipClass, loading: str) -> ShipClass:
    """Return a private copy with explicitly notional fittings where none exist."""
    result = ship.model_copy(deep=True)
    condition = next((row for row in result.loading_conditions if row.name == loading), None)
    if condition is None:
        raise ValueError(f"Unknown loading {loading!r} for {ship.class_id}")
    if result.fittings:
        return result
    result.fittings = [
        ShipFitting(fitting_id=f"SIM-BITT-{i}{suffix}", kind="bitt",
                    x_ft=fraction * result.lwl_ft, y_ft=sign * result.beam_ft / 2,
                    z_ft=condition.freeboard_ft, side=side, swl_lbf=SYNTHETIC_BITT_SWL_LBF)
        for suffix, side, sign in (("P", "port", 1), ("S", "starboard", -1))
        for i, fraction in enumerate(FITTING_STATIONS, start=1)
    ]
    result.provenance = result.provenance.model_copy(update={
        "confidence": "estimated",
        "source": "Motion training geometry; not a verified vessel fitting plan",
        "notes": result.provenance.notes + " Synthetic SIM-BITT fittings at authored fractions of LWL; arbitrary 200,000 lbf training ratings. "
        "This private session copy does not update the ship reference catalog.",
    })
    return result


def training_environment(at_utc, supplied: EnvironmentSnapshot | None = None) -> EnvironmentSnapshot:
    """Authored values are never presented as a retained observation or live feed."""
    values = (dict(wind_speed_kt=8.0, wind_gust_kt=10.0, wind_from_true_deg=195.0,
                   current_speed_kt=0.3, current_set_true_deg=15.0, water_level_mllw_ft=1.5)
              if supplied is None else {key: getattr(supplied, key) for key in (
                  "wind_speed_kt", "wind_gust_kt", "wind_from_true_deg", "current_speed_kt",
                  "current_set_true_deg", "water_level_mllw_ft", "air_density_kgm3", "water_density_kgm3")})
    return EnvironmentSnapshot(**values, valid_at_utc=at_utc, source="scenario", quality=[],
        metadata=EnvironmentMetadata(basis="scenario", source="Authored Motion training conditions",
            wind_averaging_s=60, gust_duration_s=30, wind_reference_height_m=10,
            vertical_datum="MLLW", quality="unknown"))


def norfolk_route(berth) -> MotionRoute:
    """Reuse documented water-route stations; final approach is explicitly authored."""
    stations = [  # same first five points as transit.presets.APPROACH
        ("Thimble Shoal Channel entrance", 36.9950, -76.0450, 10.0),
        ("Thimble Shoal Channel", 36.9950, -76.1600, 10.0),
        ("Hampton Roads", 36.9850, -76.2700, 6.0),
        ("Norfolk Harbor Entrance Reach", 36.9750, -76.3150, 3.0),
        ("Off Sewells Point", 36.9690, -76.3300, 2.0),
    ]
    plane = LocalPlane(berth.origin_lat, berth.origin_lon)
    bearing = math.radians(berth.face_bearing_true_deg)
    normal = bearing - math.pi / 2
    # Stay west of the neighboring pier ends, then enter the Pier 12/13 basin
    # already roughly parallel to the face. A direct line south from Sewells
    # Point crosses Piers 14/13 in NOAA's supplied shoreline geometry.
    for name, x, y, speed in (("Clear of northern pier ends", -2400.0, 3500.0, 2.0),
                               ("Outer turning approach", -2400.0, 1800.0, 1.5),
                               ("Pier basin turn", -1800.0, 600.0, 1.0),
                               ("Aligned pier approach", -900.0, 300.0, 0.7),
                               ("Off-pier holding point", berth.face_length_ft / 2, 300.0, 0.0)):
        lat, lon = plane.to_geo(0.3048 * (x * math.sin(bearing) + y * math.sin(normal)),
                                0.3048 * (x * math.cos(bearing) + y * math.cos(normal)))
        stations.append((name, lat, lon, speed))
    return MotionRoute(route_id="norfolk-channel-to-pier12", title="Norfolk channel to Pier 12 approach",
        waypoints=[MotionWaypoint(name=name, lat=lat, lon=lon, speed_kt=speed)
                   for name, lat, lon, speed in stations],
        source="Repository Norfolk transit demonstration; OSM open-water coastline and NOAA ENC Online US5ORFCC shoreline fixture; authored final approach around pier ends.",
        limitations=["Not charted channel centerlines or a pilot-approved passage plan.",
                     "Depth, bridges, exclusion zones and changing traffic are not established by this route.",
                     "Route guidance is synthetic training assistance; final docking requires explicit controls."])
