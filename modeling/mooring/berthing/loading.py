"""Point-payload mass properties and limited wall-sided hydrostatics.

First moments and parallel axes aggregate mass. Added volume = added mass/rho;
sinkage = added volume/waterplane area. GM = CB_z - CG_z + I_waterplane/volume;
small-angle righting moment = weight*GM*angle. Reference: MIT 2.019 lecture 2,
pp. 13–16, https://ocw.mit.edu/courses/2-019-design-of-ocean-systems-spring-2011/
f0cc4e483a7d4b78760f9b0908f51c44_MIT2_019S11_HydStr1.pdf .
No tank free surface, large-angle stability, squat, waves or seabed contact law.
Depth is used only inside an explicitly supplied patch covering the whole hull.
"""
import math

from mooring.core.schemas.motion_controls import LoadingSpec, MotionControlsConfig, MotionLoadingState
from mooring.mechanics.dynamics import BodyParams


def loading_state(spec: LoadingSpec, length_ft: float, beam_ft: float,
                  state=None, water_level_ft: float | None = None) -> MotionLoadingState:
    mass = spec.base_mass_slug
    cg0 = (spec.base_cg_x_ft, spec.base_cg_y_ft, spec.base_cg_z_ft)
    particles = [(p.weight_lbf/spec.gravity_fps2, (p.x_ft, p.y_ft, p.z_ft)) for p in spec.payloads]
    total = mass + sum(m for m, _ in particles)
    cg = tuple((mass*cg0[i] + sum(m*xyz[i] for m,xyz in particles))/total for i in range(3))
    izz = (spec.base_izz_slug_ft2 + mass*((cg0[0]-cg[0])**2+(cg0[1]-cg[1])**2)
           + sum(m*((xyz[0]-cg[0])**2+(xyz[1]-cg[1])**2) for m,xyz in particles))
    volume0, volume = mass/spec.water_density_slug_ft3, total/spec.water_density_slug_ft3
    sinkage = (volume-volume0)/spec.waterplane_area_ft2
    cb_z = (volume0*spec.base_cb_z_ft + (volume-volume0)*sinkage/2)/volume
    gmt = cb_z-cg[2]+spec.waterplane_ixx_ft4/volume
    gml = cb_z-cg[2]+spec.waterplane_iyy_ft4/volume
    if min(gmt, gml) <= 0:
        raise ValueError("loading has nonpositive GM; small-angle model cannot resolve unstable equilibrium")
    # Baseline buoyancy balances baseline CG. The new immersed slice has its
    # horizontal centroid at the waterplane origin; only added first moments
    # drive new trim/list even when baseline CG is offset from the ship origin.
    roll = -sum(m*xyz[1] for m,xyz in particles)/(total*gmt)
    pitch = sum(m*xyz[0] for m,xyz in particles)/(total*gml)
    if max(abs(math.degrees(roll)), abs(math.degrees(pitch))) > spec.max_abs_attitude_deg:
        raise ValueError("loading exceeds supplied small-angle attitude boundary")
    if sinkage > spec.max_sinkage_fraction*spec.base_draft_ft:
        raise ValueError("loading exceeds supplied wall-sided sinkage boundary")
    mean = spec.base_draft_ft+sinkage
    fwd, aft = mean+pitch*length_ft/2, mean-pitch*length_ft/2
    maximum = mean+abs(pitch)*length_ft/2+abs(roll)*beam_ft/2
    if mean-abs(pitch)*length_ft/2-abs(roll)*beam_ft/2 <= 0:
        raise ValueError("loading exposes the rectangular keel; hydrostatic approximation unsupported")
    reasons = [{"code": "SYNTHETIC_LOADING_MODEL", "message":
        "Unqualified point payloads, fixed waterplane and wall-sided small-angle hydrostatics; no free-surface, squat or waves."}]
    depth = uncertainty = ukc = lower = None
    patch = spec.local_depth
    covered = False
    if patch is not None and state is not None:
        x, y, yaw = state[:3]
        c, sn = math.cos(yaw), math.sin(yaw)
        corners = [(x+c*dx-sn*dy, y+sn*dx+c*dy)
                   for dx in (-length_ft/2, length_ft/2) for dy in (-beam_ft/2, beam_ft/2)]
        covered = all(patch.x_min_ft <= xx <= patch.x_max_ft and patch.y_min_ft <= yy <= patch.y_max_ft
                      for xx,yy in corners)
        if covered:
            depth, uncertainty = patch.depth_mllw_ft, patch.uncertainty_ft
            if water_level_ft is not None:
                ukc = depth+water_level_ft-maximum
                lower = ukc-uncertainty if uncertainty is not None else None
    if not covered:
        reasons.append({"code": "LOCAL_DEPTH_UNAVAILABLE", "message":
            "No supplied depth patch covers the complete hull footprint; under-keel clearance unavailable."})
    elif uncertainty is None:
        reasons.append({"code": "DEPTH_UNCERTAINTY_UNAVAILABLE", "message":
            "Local depth has no uncertainty bound; conservative under-keel clearance unavailable."})
    if covered and water_level_ft is None:
        reasons.append({"code": "UKC_WATER_LEVEL_UNAVAILABLE", "message": "Water level unavailable; under-keel clearance unavailable."})
    invalid = ukc is not None and ukc <= 0 or lower is not None and lower <= 0
    if invalid:
        reasons.append({"code": "UNDER_KEEL_CONTACT_POSSIBLE", "message":
            "Hull reaches supplied depth or its uncertainty bound; seabed contact dynamics not modeled."})
    return MotionLoadingState(basis=spec.basis, source=spec.source, payloads=spec.payloads,
        total_mass_slug=total, total_weight_lbf=total*spec.gravity_fps2,
        cg_x_ft=cg[0], cg_y_ft=cg[1], cg_z_ft=cg[2], izz_cg_slug_ft2=izz,
        izz_origin_slug_ft2=izz+total*(cg[0]**2+cg[1]**2), sinkage_ft=sinkage,
        mean_draft_ft=mean, draft_fwd_ft=fwd, draft_aft_ft=aft, maximum_draft_ft=maximum,
        roll_deg=math.degrees(roll), pitch_deg=math.degrees(pitch), gm_transverse_ft=gmt, gm_longitudinal_ft=gml,
        local_depth_mllw_ft=depth, depth_uncertainty_ft=uncertainty, under_keel_ft=ukc, under_keel_lower_ft=lower,
        validity={"state": "invalid" if invalid else "limited", "reasons": reasons})


def body_params(spec: LoadingSpec, loaded: MotionLoadingState) -> BodyParams:
    return BodyParams(mass_slug=loaded.total_mass_slug, izz_slug_ft2=loaded.izz_cg_slug_ft2,
        cg_x_ft=loaded.cg_x_ft, cg_y_ft=loaded.cg_y_ft,
        added_surge=spec.added_surge_slug, added_sway=spec.added_sway_slug, added_yaw=spec.added_yaw_slug_ft2,
        damping_lin=(spec.damping_surge_lbf_per_fps, spec.damping_sway_lbf_per_fps,
                     spec.damping_yaw_ftlbf_per_radps), qualification="synthetic")


def synthetic_motion_controls(ship, loading_name="full_load") -> MotionControlsConfig:
    """Explicit fictional body, not identified vessel coefficients.

    Catalog displacement/dimensions size the demonstration. Uniform box yaw
    inertia; .85 rectangular waterplane; CB at half draft, CG at waterline.
    Added mass ratios .05/.5/.1, damping time scales 50/12/25 s. Engine thrust
    per shaft .006*weight, astern half, thrusters .001*weight. These and every
    rudder/slew coefficient below are authored SYNTHETIC assumptions. No seabed.
    """
    condition = next((x for x in ship.loading_conditions if x.name == loading_name), None)
    if condition is None:
        raise ValueError(f"unknown loading condition: {loading_name}")
    g, rho = 32.174, 1.99
    mass, length, beam = condition.displacement_lt*2240/g, ship.lwl_ft, ship.beam_ft
    draft = (condition.draft_fwd_ft+condition.draft_aft_ft)/2
    inertia = mass*(length**2+beam**2)/12
    area, weight = .85*length*beam, mass*g
    source = "synthetic-motion-demo-v1: authored assumptions scaled by seed catalog geometry; not vessel data"
    return MotionControlsConfig.model_validate({
        "tug_standoff_ft": 45.0, "tug_slew_s": 5.0,
        "loading": dict(basis="synthetic", source=source, base_mass_slug=mass, base_izz_slug_ft2=inertia,
            base_cg_x_ft=0, base_cg_y_ft=0, base_cg_z_ft=0, base_draft_ft=draft, base_cb_z_ft=-draft/2,
            waterplane_area_ft2=area, waterplane_ixx_ft4=area*beam**2/12,
            waterplane_iyy_ft4=area*length**2/12, water_density_slug_ft3=rho, gravity_fps2=g,
            added_surge_slug=.05*mass, added_sway_slug=.5*mass, added_yaw_slug_ft2=.1*inertia,
            damping_surge_lbf_per_fps=mass/50, damping_sway_lbf_per_fps=mass/12,
            damping_yaw_ftlbf_per_radps=inertia/25, max_abs_attitude_deg=5, max_sinkage_fraction=.1),
        "propulsion": dict(basis="synthetic", source=source, max_ahead_thrust_lbf=.006*weight,
            max_astern_thrust_lbf=.003*weight, shaft_x_ft=-.4*length, shaft_y_ft=.2*beam, engine_slew_per_s=.2,
            rudder_x_ft=-.45*length, rudder_area_ft2=.03*beam**2, rudder_lift_slope_per_rad=2,
            rudder_max_lift_coefficient=1, rudder_max_force_lbf=.003*weight,
            rudder_max_deg=35, rudder_slew_degps=5, propwash_fps_at_full_ahead=10,
            bow_thruster_x_ft=.4*length, bow_thruster_max_lbf=.001*weight,
            stern_thruster_x_ft=-.4*length, stern_thruster_max_lbf=.001*weight,
            thruster_slew_per_s=.5, water_density_slug_ft3=rho)})
