"""Every constant of the S6 transit model with its source and status (the table in docs/PORT_TRANSIT.md is generated
from the same list; `test_s6_docs.py` keeps them in step).

Status vocabulary: PUBLISHED = formula from the cited publication used as published (still a regression for the
hull form it was fitted to, not this ship); ASSUMED = labeled engineering assumption with no source data for these
ships; NUMERICAL = a numerical safeguard, not physics. Nothing here is a trial or captive-model result.
"""

from __future__ import annotations

from dataclasses import dataclass

LT_KG = 1016.0469088            # long ton in kg
RHO_WATER_DEFAULT = 1025.0      # kg/m3 when no environment supplies water density (labeled)
NU_WATER = 1.19e-6              # m2/s kinematic viscosity, seawater ~15 C (labeled)
FT_M = 0.3048
KT_MPS = 0.5144444
LBF_N = 4.4482216

IZ_RADIUS_FACTOR = 0.25         # Iz = m (0.25 L)^2
ADDED_SURGE = 0.05              # X_udot = -0.05 m
U_FLOOR = 0.25                  # m/s floor on U in the Clarke dimensionalisation
CD_CROSSFLOW = 0.8              # cross-flow drag coefficient (strip theory)
N_STRIPS = 20
FORM_K = 0.15                   # (1+k) form factor
C_A = 0.0004                    # incremental/correlation allowance
WAKE_W = 0.2
PROP_D_OVER_T = 0.6
RACE_FRACTION = 0.7
RUDDER_ASPECT = 1.5
RUDDER_STALL_DEG = 30.0
A_H = 0.25                      # MMG rudder-induced hull force fraction
X_H_OVER_L = -0.4
X_R_OVER_L = -0.5
T_R = 0.28                      # MMG thrust-deduction-like rudder drag factor
GAMMA_R = 0.5                   # flow straightening at the rudder
THRUSTER_X_OVER_L = 0.4
THRUSTER_FADE_MPS = 3.0
THRUSTER_SLEW_S = 5.0
TUG_SLEW_S = 10.0
EPOCH_UTC = "2000-01-01T00:00:00Z"

# Twin-screw / twin-rudder public configuration of the four catalog classes (DDG-51 and CG-47: twin shafts, twin rudders;
# LHD-1: twin shafts, twin rudders; CVN-68: four shafts, TWO rudders). Labeled; a class not listed has one rudder.
RUDDER_COUNT = {"DDG-51-FIIA": 2, "CG-47": 2, "LHD-1": 2, "CVN-68": 2}
CB_INCONSISTENT_FRACTION = 0.20  # catalog Cb replaced by displacement-derived Cb when they differ by more than this

DECEL_PLAN_FRACTION = 0.7       # arrival planner assumes this fraction of the astern-thrust deceleration (resistance help ignored)

DEFAULT_MAX_SPEED_KT = {  # public nominal maximum speeds, NOT trial results
    "DDG-51-FIIA": 30.0, "CG-47": 30.0, "LHD-1": 22.0, "CVN-68": 30.0,
}


@dataclass(frozen=True)
class Coef:
    name: str
    value: str
    source: str
    status: str


COEFFICIENT_TABLE: list[Coef] = [
    Coef("Mass m", "displacement_lt x 1016.047 kg", "ship catalog loading condition", "PUBLISHED catalog value (itself an estimate)"),
    Coef("Yaw inertia Iz", "m (0.25 L)^2", "common radius-of-gyration rule of thumb", "ASSUMED"),
    Coef("Longitudinal CG xG", "0 (midships)", "simplification", "ASSUMED"),
    Coef("Surge added mass X_udot", "-0.05 m", "common naval-architecture rule of thumb", "ASSUMED"),
    Coef("Sway/yaw added mass and cross derivatives Y_vdot, Y_rdot, N_vdot, N_rdot", "Clarke et al. regressions", "Clarke, Gedling & Hine (1983), Trans. RINA 125", "PUBLISHED regression (hull-form range not checked for these ships)"),
    Coef("Linear derivatives Y_v, Y_r, N_v, N_r", "Clarke et al. regressions in L=LWL, B, T, Cb", "Clarke, Gedling & Hine (1983)", "PUBLISHED regression"),
    Coef("U floor in dimensionalisation", f"{U_FLOOR} m/s", "numerical", "NUMERICAL"),
    Coef("Cross-flow drag Cd", f"{CD_CROSSFLOW}, {N_STRIPS} strips", "Hoerner-type flat-plate value for a ship section", "ASSUMED"),
    Coef("Wetted surface S", "1.7 L T + V/T", "Mumford (1965)", "PUBLISHED regression"),
    Coef("Friction line C_F", "0.075/(log10 Re - 2)^2", "ITTC-57", "PUBLISHED"),
    Coef("Form factor (1+k)", f"{1 + FORM_K}", "typical slender-hull range 1.1-1.3", "ASSUMED"),
    Coef("Allowance C_A", f"{C_A}", "typical 0.0002-0.0006", "ASSUMED"),
    Coef("Wave-making resistance", "not modeled", "omitted", "LIMITATION"),
    Coef("Kinematic viscosity / water density", f"{NU_WATER} m2/s / environment value or {RHO_WATER_DEFAULT} kg/m3", "seawater ~15 C", "ASSUMED"),
    Coef("Max speed (calibrates T_max)", "30 kt DDG-51, CG-47, CVN-68; 22 kt LHD-1", "public nominal maximum speed", "ASSUMED; not a trial result"),
    Coef("Astern thrust fraction", "0.6 default (request)", "request value", "ASSUMED"),
    Coef("Engine time constant", "20 s default (request)", "request value", "ASSUMED"),
    Coef("Wake fraction w", f"{WAKE_W}", "typical 0.1-0.3", "ASSUMED"),
    Coef("Propeller diameter D", f"{PROP_D_OVER_T} T", "typical 0.5-0.7 T", "ASSUMED"),
    Coef("Race fraction at rudder", f"{RACE_FRACTION}", "between disk (0.5) and fully contracted slipstream (1.0) of momentum theory", "ASSUMED"),
    Coef("Rudder area A_R (per rudder)", "(T L/100)(1 + 25 (B/L)^2)", "DNV rule guidance for rudder area", "PUBLISHED guidance, used as a size estimate"),
    Coef("Arrival planning deceleration", f"{DECEL_PLAN_FRACTION} x astern_fraction x T_max / m11 (the arrival ramp is lengthened when the linear ramp would need more)", "autopilot design choice (planning margin), not ship data", "ASSUMED"),
    Coef("Rudder count", "2 for DDG-51, CG-47, LHD-1, CVN-68; equivalent rudder = count x area, each in its own propeller race (thrust T/count per race)", "public configuration, area per rudder from DNV guidance", "ASSUMED (public configuration); one rudder for any other class"),
    Coef("Block coefficient for the Clarke terms", "catalog Cb, or m/(rho L B T) when the two differ by more than 20 %", "displacement consistency check with the catalog draft (which may include the sonar dome; the catalog cannot distinguish)", "DERIVED; DDG-51 0.51 -> 0.35, CG-47 0.47 -> 0.36, LHD-1 and CVN-68 keep catalog values"),
    Coef("Rudder aspect ratio", f"{RUDDER_ASPECT}", "typical", "ASSUMED"),
    Coef("Rudder lift slope", "f_a = 6.13 L/(2.25 + L)", "Fujii (1960) as used in the MMG standard method (Yasukawa & Yoshimura 2015)", "PUBLISHED"),
    Coef("Rudder stall angle", f"{RUDDER_STALL_DEG} deg clamp on effective angle", "typical", "ASSUMED"),
    Coef("Rudder max angle / rate", "35 deg / 2.33 deg/s defaults (request)", "steering-gear criterion 35 to 30 deg in 28 s", "ASSUMED"),
    Coef("a_H, x_H, t_R, x_R, gamma_R", f"{A_H}, {X_H_OVER_L} L, {T_R}, {X_R_OVER_L} L, {GAMMA_R}", "MMG standard form (Yasukawa & Yoshimura 2015), typical magnitudes", "ASSUMED values"),
    Coef("Bow thruster", f"at +{THRUSTER_X_OVER_L} L, fade to 0 at {THRUSTER_FADE_MPS} m/s, slew {THRUSTER_SLEW_S} s", "typical", "ASSUMED"),
    Coef("Tug capacity", "bollard_pull_ahead_lbf of the catalog tug, any direction", "tug catalog (rough rules of thumb)", "ASSUMED"),
    Coef("Tug slew", f"{TUG_SLEW_S} s from zero to full pull", "typical", "ASSUMED"),
    Coef("Wind", "UFC 4-159-03 loads on the apparent wind; sustained-to-30 s conversion applied by the loads module", "UFC 4-159-03", "PUBLISHED, with deep-water/zero-current snapshot"),
]
