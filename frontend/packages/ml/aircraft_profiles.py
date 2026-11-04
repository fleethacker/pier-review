"""
Aircraft Aerodynamic Profiles
=============================
Each aircraft has unique physical properties that determine how it responds to wind.
These profiles are used by both the Ray simulation pipeline and the in-app wind physics.

Key insight: A correction model trained on one aircraft CANNOT be used for another.
The X-47B (heavy, low-drag stealth UCAV) responds completely differently to wind
than a Cessna 172 (light, high-drag general aviation aircraft). This is why we need
a Ray cluster — to simulate and train separate models for each aircraft type.

Aerodynamic Parameters:
- wingspan: Wing span in meters — affects lateral wind force area
- length: Fuselage length in meters — affects headwind drag area
- mass: Maximum takeoff weight in kg — heavier = more inertia, less wind effect
- max_speed: Maximum airspeed in km/h — determines speed envelope
- frontal_area: Cross-sectional area facing forward in m² — key for drag calculation
- side_area: Cross-sectional area from the side in m² — key for crosswind force
- drag_coeff: Drag coefficient (Cd) — lower = more aerodynamic (stealth aircraft ~0.02)
- lift_coeff: Lift coefficient (Cl) — affects vertical response to wind
- wing_loading: Mass / wing area in kg/m² — higher = more stable in turbulence
"""

AIRCRAFT_PROFILES = {
    "x47b": {
        "name": "X-47B UCAV",
        "description": "Northrop Grumman unmanned combat air vehicle. Stealth design with "
                       "blended wing body gives extremely low drag but limited control surfaces "
                       "make it sensitive to sudden gusts at low speed.",
        "glb": "x47b.glb",

        # Physical dimensions (from actual X-47B specifications)
        "wingspan": 18.92,          # meters (62.1 ft)
        "length": 11.63,            # meters (38.2 ft)
        "height": 3.10,             # meters (10.2 ft)
        "wing_area": 86.0,          # m² (estimated from planform)

        # Mass properties
        "mass": 20215,              # kg (44,567 lb) MTOW
        "empty_mass": 6350,         # kg (14,000 lb)

        # Performance
        "max_speed": 1035,          # km/h (Mach 0.9 at altitude)
        "cruise_speed": 850,        # km/h
        "ceiling": 12200,           # meters (40,000 ft)

        # Aerodynamic coefficients (estimated from stealth BWB design)
        "frontal_area": 3.2,        # m² — small due to blended body
        "side_area": 12.5,          # m² — larger lateral profile
        "drag_coeff": 0.022,        # Very low — stealth shape optimized for low RCS/drag
        "lift_coeff": 0.45,         # Moderate — BWB generates lift from body
        "wing_loading": 235.0,      # kg/m² — high, means stable in turbulence

        # Simulation tuning
        "wind_sensitivity": 0.6,    # Lower = less affected by wind (heavy aircraft)
        "correction_inertia": 0.8,  # Higher = slower to respond to corrections
    },

    "cessna172": {
        "name": "Cessna 172 Skyhawk",
        "description": "Most produced aircraft in history. Light general aviation aircraft "
                       "with high wing design. Very susceptible to crosswinds and turbulence "
                       "due to low mass and high drag profile.",
        "glb": "cessna172.glb",

        # Physical dimensions
        "wingspan": 11.0,           # meters (36.1 ft)
        "length": 8.28,             # meters (27.2 ft)
        "height": 2.72,             # meters (8.9 ft)
        "wing_area": 16.2,          # m²

        # Mass properties
        "mass": 1111,               # kg (2,450 lb) MTOW
        "empty_mass": 743,          # kg (1,638 lb)

        # Performance
        "max_speed": 302,           # km/h (163 kts)
        "cruise_speed": 226,        # km/h (122 kts)
        "ceiling": 4100,            # meters (13,500 ft)

        # Aerodynamic coefficients
        "frontal_area": 1.8,        # m² — blunt nose, fixed gear
        "side_area": 5.5,           # m²
        "drag_coeff": 0.034,        # Higher — fixed landing gear, struts
        "lift_coeff": 0.50,         # Good lift — high wing design
        "wing_loading": 68.6,       # kg/m² — low, very affected by gusts

        # Simulation tuning
        "wind_sensitivity": 1.5,    # High — light aircraft gets blown around
        "correction_inertia": 0.3,  # Low — responds quickly to inputs
    },

    "mq9_reaper": {
        "name": "MQ-9 Reaper",
        "description": "General Atomics hunter-killer UAV. Long endurance, medium altitude. "
                       "Large wingspan for loitering makes it moderately affected by crosswinds "
                       "but the turboprop provides good speed recovery.",
        "glb": "mq9.glb",

        # Physical dimensions
        "wingspan": 20.12,          # meters (66 ft)
        "length": 11.0,             # meters (36 ft)
        "height": 3.81,             # meters (12.5 ft)
        "wing_area": 32.5,          # m² (estimated)

        # Mass properties
        "mass": 4760,               # kg (10,500 lb) MTOW
        "empty_mass": 2223,         # kg (4,900 lb)

        # Performance
        "max_speed": 482,           # km/h (260 kts)
        "cruise_speed": 313,        # km/h (170 kts)
        "ceiling": 15240,           # meters (50,000 ft)

        # Aerodynamic coefficients
        "frontal_area": 2.1,        # m²
        "side_area": 8.0,           # m²
        "drag_coeff": 0.028,        # Moderate — clean design but not stealth
        "lift_coeff": 0.55,         # High — long wings for loitering
        "wing_loading": 146.5,      # kg/m² — moderate

        # Simulation tuning
        "wind_sensitivity": 1.0,    # Baseline
        "correction_inertia": 0.5,  # Moderate response
    },
}


def get_profile(aircraft_id: str) -> dict:
    """Get aerodynamic profile for an aircraft type."""
    if aircraft_id not in AIRCRAFT_PROFILES:
        raise ValueError(
            f"Unknown aircraft '{aircraft_id}'. "
            f"Available: {list(AIRCRAFT_PROFILES.keys())}"
        )
    return AIRCRAFT_PROFILES[aircraft_id]


def list_aircraft() -> list:
    """List all available aircraft profiles."""
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in AIRCRAFT_PROFILES.items()
    ]
