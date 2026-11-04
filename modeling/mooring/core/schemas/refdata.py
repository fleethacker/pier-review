"""Reference data: ship classes, mooring line specs, berths (piers) and tugs (module M2).

Frames:
- Ship frame: origin at midships, centerline, waterline. +x forward, +y to port, +z up.
- Berth frame: origin at the berth reference point on the pier face. Standing on the pier looking out over
  the water, +y points into the water and +x runs to your right. +z is up from MLLW.
  `Berth.face_bearing_true_deg` is the true bearing of +x and links the berth frame to geo.
  A ship moored starboard side to has its bow toward +x; port side to, bow toward -x.
"""

from typing import Literal

from pydantic import Field

from .common import Model, Provenance

# ---------- Ships ----------


class LoadingCondition(Model):
    name: str = Field(examples=["full_load"])
    displacement_lt: float = Field(gt=0)
    draft_fwd_ft: float = Field(gt=0)
    draft_aft_ft: float = Field(gt=0)
    freeboard_ft: float = Field(gt=0, description="Typical freeboard at midships.")


class ShipFitting(Model):
    """A bitt, chock or cleat on the ship. Coordinates in the ship frame."""

    fitting_id: str = Field(examples=["BITT-1S"])
    kind: Literal["bitt", "chock", "cleat", "recessed_bitt"]
    x_ft: float
    y_ft: float
    z_ft: float = Field(description="Height above the waterline at the reference loading.")
    side: Literal["port", "starboard", "centerline"]
    swl_lbf: float | None = Field(default=None, description="Safe working load (NSTM Tables 582-5-3/4).")
    max_rope_circ_in: float | None = None
    paired_chock_id: str | None = Field(default=None, description="Chock a line from this bitt leads through.")


class PushPoint(Model):
    """Hull location marked for tug pushing. x in the ship frame."""

    push_point_id: str = Field(examples=["PP-FWD-P"])
    x_ft: float
    side: Literal["port", "starboard"]
    max_force_lbf: float = Field(gt=0)


class LineInventoryItem(Model):
    spec_id: str = Field(examples=["NYLON-DB-7IN"])
    count: int = Field(ge=0)


class ShipClass(Model):
    class_id: str = Field(examples=["DDG-51-FIIA"])
    name: str
    hull_type: str = Field(examples=["DDG"])
    loa_ft: float = Field(gt=0)
    lwl_ft: float = Field(gt=0)
    beam_ft: float = Field(gt=0)
    block_coefficient: float = Field(gt=0, le=1)
    loading_conditions: list[LoadingCondition]
    wind_area_lateral_ft2: float = Field(gt=0, description="Side profile area above the waterline.")
    wind_area_frontal_ft2: float = Field(gt=0)
    hull_wind_area_lateral_ft2: float = Field(gt=0, description="Hull-only part of the lateral area (UFC 4-159-03).")
    superstructure_height_ft: float | None = Field(default=None, gt=0, description="Superstructure height above the reference waterline; estimated from profile areas when absent.")
    midship_coefficient: float | None = Field(default=None, gt=0, le=1, description="Immersed midship area / (beam * draft); UFC Eq. 4-14.")
    propeller_expanded_area_ft2: float | None = Field(default=None, ge=0, description="Total expanded blade area; zero for no exposed propellers, estimated when absent.")
    wetted_surface_ft2: float | None = Field(default=None, gt=0, description="Wetted surface at full_load; other loadings and missing values use UFC Eq. 4-18.")
    wind_drag_class: Literal["hull_dominated", "typical", "extensive_superstructure"] = Field(
        description="UFC 4-159-03 Table 4-2 drag class."
    )
    fittings: list[ShipFitting] = Field(default_factory=list)
    push_points: list[PushPoint] = Field(default_factory=list)
    standard_line_outfit: list[LineInventoryItem] = Field(default_factory=list)
    mst_class: Literal["II", "IIA"] = Field(description="CVN 68, LHA 1 and LHD 1/5 are IIA (NSTM 582-1.2.2.2).")
    provenance: Provenance


class ShipClassSummary(Model):
    class_id: str
    name: str
    hull_type: str
    loa_ft: float
    beam_ft: float
    mst_class: Literal["II", "IIA"]
    has_fittings: bool


# ---------- Mooring lines ----------


class LineSpec(Model):
    spec_id: str = Field(examples=["NYLON-DB-7IN"])
    material: Literal["nylon", "polyester", "aramid", "uhmwpe", "wire"]
    construction: Literal["three_strand", "plaited", "double_braid", "twelve_strand", "four_strand", "wire"]
    size_circ_in: float = Field(gt=0)
    mbs_lbf: float = Field(gt=0, description="Minimum breaking strength, dry, one part.")
    load_elongation: list[tuple[float, float]] = Field(
        description="Stretch curve as [fraction of MBS, strain] pairs, starting at [0, 0]."
    )
    wet_strength_factor: float = Field(default=1.0, gt=0, le=1, description="0.85 for nylon (NSTM 582-2.4.2.i).")
    weight_lb_per_100ft: float | None = None
    provenance: Provenance


# ---------- Berths ----------

PierFittingKind = Literal[
    "bollard_special_a",
    "bollard_special_b",
    "bollard_horn",
    "double_bitt_lip",
    "low_double_bitt",
    "cleat_42",
    "cleat_30",
]


class PierFitting(Model):
    """A bollard, bitt or cleat on the pier. Coordinates in the berth frame (negative y = on the deck)."""

    fitting_id: str = Field(examples=["P12N-B12"])
    kind: PierFittingKind
    x_ft: float
    y_ft: float
    capacity_nominal_lbf: float = Field(gt=0, description="Working capacity (NSTM Table 582-5-6, 'Nom.').")
    capacity_horizontal_lbf: float | None = None
    capacity_45deg_lbf: float | None = None
    condition: Literal["good", "suspect", "do_not_use"] = "good"
    occupied_by: str | None = Field(default=None, description="Another ship's line already on this fitting.")


class Fender(Model):
    """Camel, separator or fender along the face. x in the berth frame."""

    fender_id: str
    kind: Literal["camel", "pneumatic", "foam", "separator"]
    x_ft: float
    length_ft: float = Field(gt=0)
    standoff_ft: float = Field(ge=0, description="Distance from pier face to the ship's side.")
    stiffness_lbf_per_ft: float = Field(gt=0)
    rated_energy_ftlbf: float = Field(gt=0)


class DepthPoint(Model):
    x_ft: float
    depth_mllw_ft: float = Field(gt=0)


class EnvStations(Model):
    """NOAA CO-OPS station ids that feed this berth's environment."""

    wind: str = Field(examples=["8638614"])
    current: str = Field(examples=["cb0402"])
    water_level: str = Field(examples=["8638610"])


class Berth(Model):
    berth_id: str = Field(examples=["NAVSTA-NORFOLK-P12-N"])
    name: str
    face_bearing_true_deg: float = Field(ge=0, lt=360, description="True bearing of the berth frame's +x axis.")
    origin_lat: float
    origin_lon: float
    face_length_ft: float = Field(gt=0)
    deck_height_mllw_ft: float
    depth_profile: list[DepthPoint]
    fittings: list[PierFitting]
    fenders: list[Fender] = Field(default_factory=list)
    structure: Literal["open_pile", "solid"] = "open_pile"
    env_station_ids: EnvStations
    provenance: Provenance


class BerthSummary(Model):
    berth_id: str
    name: str
    face_length_ft: float
    min_depth_mllw_ft: float
    fitting_count: int
    confidence: Literal["published", "estimated", "mock", "vision"]


class BerthCreated(Model):
    berth_id: str


# ---------- Tugs ----------


class TugSpec(Model):
    tug_id: str = Field(examples=["T1"])
    name: str
    propulsion: Literal["conventional", "asd", "tractor", "vsp"]
    power_hp: float = Field(gt=0)
    bollard_pull_ahead_lbf: float = Field(gt=0)
    bollard_pull_astern_lbf: float = Field(gt=0)
    provenance: Provenance
