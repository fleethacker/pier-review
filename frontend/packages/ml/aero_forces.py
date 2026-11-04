"""
Aerodynamic Force Model for ML Training
========================================
Computes aerodynamic forces and moments from the aircraft state
and wind conditions using standard stability derivative formulations.

The force model is consistent with the CFD simulations:
- V_aero = V_aircraft + V_wind (vector sum)
- α (angle of attack) from vertical gusts
- β (sideslip angle) from crosswind
- Forces computed from standard coefficients

This replaces the simplified WindModel used previously and ensures
the ML training data is physically consistent with the CFD flow fields.

Reference: MIT OCW 16.333, Stengel "Flight Dynamics"
"""

import numpy as np
from typing import Dict


def compute_aero_state(
    aircraft_speed: float,
    heading_rad: float,
    wind_speed: float,
    wind_dir_deg: float,
    vertical_gust: float = 0.0,
) -> Dict[str, float]:
    """
    Compute the aerodynamic state from combined aircraft + wind velocity.

    Returns effective airspeed, angle of attack, and sideslip angle.

    Args:
        aircraft_speed: Aircraft TAS in m/s
        heading_rad: Aircraft heading in radians
        wind_speed: Environmental wind speed in m/s
        wind_dir_deg: Wind direction relative to aircraft (0=head, 90=cross)
        vertical_gust: Vertical wind component in m/s

    Returns:
        Dict with V_aero, alpha, beta, and velocity components
    """
    wind_rad = np.radians(wind_dir_deg)

    # Wind components in aircraft body frame
    headwind = wind_speed * np.cos(wind_rad)
    crosswind = wind_speed * np.sin(wind_rad)

    # Effective airspeed
    V_aero = np.sqrt((aircraft_speed + headwind)**2 + crosswind**2 + vertical_gust**2)

    # Sideslip angle β
    beta = np.arctan2(crosswind, aircraft_speed + headwind) if (aircraft_speed + headwind) > 0.1 else 0.0

    # Angle of attack perturbation from vertical gust
    alpha = np.arctan2(vertical_gust, aircraft_speed + headwind) if (aircraft_speed + headwind) > 0.1 else 0.0

    # Dynamic pressure q = 0.5 * rho * V²
    rho = 1.225  # kg/m³ at sea level
    q = 0.5 * rho * V_aero**2

    return {
        "V_aero": V_aero,
        "alpha": alpha,
        "beta": beta,
        "q": q,
        "headwind": headwind,
        "crosswind": crosswind,
    }


def compute_wind_forces(
    aircraft_profile: dict,
    aero_state: dict,
) -> Dict[str, float]:
    """
    Compute wind-induced force perturbations using stability derivatives.

    These are the PERTURBATION forces — the forces caused by wind
    that deviate from the trim (no-wind) condition. These are what
    the ML correction model needs to learn to counteract.

    Force equations (linearized about trim):
        ΔL = C_L_α · Δα · q · S                (lift perturbation)
        ΔD = C_D · Δq · S                        (drag perturbation)
        ΔY = C_Y_β · β · q · S                   (side force)
        ΔM_pitch = C_m_α · Δα · q · S · c̄       (pitching moment)
        ΔM_yaw = C_n_β · β · q · S · b           (yawing moment)

    Args:
        aircraft_profile: Dict from aircraft_profiles.py
        aero_state: Dict from compute_aero_state()

    Returns:
        Dict with force/moment perturbations and recommended corrections
    """
    q = aero_state["q"]
    alpha = aero_state["alpha"]
    beta = aero_state["beta"]
    S = aircraft_profile["wing_area"]
    b = aircraft_profile["wingspan"]
    mass = aircraft_profile["mass"]
    Cd = aircraft_profile["drag_coeff"]
    Cl = aircraft_profile["lift_coeff"]

    # Stability derivatives (typical values for combat UAV)
    C_L_alpha = 4.5      # /rad — lift curve slope
    C_Y_beta = -0.8      # /rad — side force due to sideslip
    C_m_alpha = -0.5      # /rad — pitch stiffness
    C_n_beta = 0.12       # /rad — yaw stiffness (weathercock)

    # Force perturbations (Newtons)
    delta_lift = C_L_alpha * alpha * q * S
    delta_drag = Cd * q * S  # Total drag at this q
    delta_side = C_Y_beta * beta * q * S
    delta_pitch_moment = C_m_alpha * alpha * q * S * (S / b)  # Using S/b as approx c_bar
    delta_yaw_moment = C_n_beta * beta * q * S * b

    # Convert to accelerations (F = ma)
    g = 9.81
    heading_acceleration = delta_yaw_moment / (mass * b)  # rad/s²
    speed_perturbation = -delta_drag / mass  # m/s² (drag opposes motion)
    altitude_acceleration = delta_lift / mass - g  # m/s² (lift minus weight)
    lateral_acceleration = delta_side / mass  # m/s²

    # Optimal corrections to counteract wind perturbations
    # These are proportional corrections that the ML model should learn
    heading_correction = -np.degrees(beta) * 0.5  # Correct sideslip
    throttle_correction = aero_state["headwind"] * 0.3  # Compensate headwind drag
    pitch_correction = -np.degrees(alpha) * 0.3  # Correct AoA perturbation

    return {
        "delta_lift": delta_lift,
        "delta_drag": delta_drag,
        "delta_side": delta_side,
        "heading_acceleration": heading_acceleration,
        "speed_perturbation": speed_perturbation,
        "altitude_acceleration": altitude_acceleration,
        "lateral_acceleration": lateral_acceleration,
        "heading_correction": np.clip(heading_correction, -15, 15),
        "throttle_correction": np.clip(throttle_correction, -50, 50),
        "pitch_correction": np.clip(pitch_correction, -10, 10),
    }
