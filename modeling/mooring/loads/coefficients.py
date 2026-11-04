"""UFC 4-159-03 (12 March 2020) constants, plus explicitly identified estimates.

Equation 4-3's missing harmonic and the angle-folding typos are resolved against
UFC 4-159-03 (2005, Change 2, 2016), Eq. (4) and longitudinal shape definitions.
NSTM Table 582-3-1 bearings use the same NCEL/UFC flow-TOWARD, counterclockwise
convention (Figure 4-2): 0 degrees is wind from astern. Convert those bearings to
API clockwise wind-FROM bearings with (180 - b) % 360.
No constants are calibrated to the seed ships.
"""

REFERENCE_HEIGHT_FT = 10 / 0.3048  # Eq. 4-2, p. 55: 10 m (use exact unit conversion)
HEIGHT_EXPONENT = 2 / 7  # Eq. 4-2, p. 55
WIND_CLASS = {"hull_dominated": 0.82, "typical": 0.92, "extensive_superstructure": 1.02}  # Table 4-2
TRANSVERSE_HARMONIC = 5  # 2016 Eq. (4), p. 59; matches 2020 Figure 4-4
TRANSVERSE_WEIGHT = 0.05  # Eq. 4-3, p. 55
TRANSVERSE_NORMALIZATION = 0.95  # Eq. 4-3
LONGITUDINAL_HARMONIC = 5  # Eq. 4-6, p. 64
LONGITUDINAL_WEIGHT = 0.1  # Eq. 4-6
LONGITUDINAL_NORMALIZATION = 0.9  # Eq. 4-6
# Table 4-3, p. 63: (bow-on, stern-on)
WIND_LONGITUDINAL = {"hull_dominated": (0.4, 0.4), "typical": (0.7, 0.6),
                     "extensive_superstructure": (0.7, 0.8)}
# Table 4-4, p. 63: angle in UFC's flow-TOWARD, counterclockwise frame
WIND_CROSSING = {"hull_dominated": 60.0, "typical": 90.0, "extensive_superstructure": 70.0}
# Table 4-5, p. 66: (zero angle, negative peak magnitude, positive peak)
WIND_YAW = {"destroyer": (68.0, 0.02, 0.12), "carrier": (90.0, 0.068, 0.072),
            "midships": (90.0, 0.1, 0.1)}
DEEP_CURRENT_FACTOR = 0.22  # Eq. 4-11, p. 71
SHALLOW_CURRENT_COEFFICIENT = 3.2  # Eq. 4-10 discussion and Figure 4-9, pp. 70–71
CURRENT_DEPTH_EXPONENT = 2  # Eq. 4-10 discussion, p. 71
MAX_DRAFT_DEPTH_RATIO = 1.0  # Figure 4-9, endpoint; grounded cases are warned, not certified
CURRENT_LIMIT_FPS = 1.5 / 0.3048  # Section 4-5.1, p. 72
FORM_DRAG = 0.1  # Eq. 4-16, p. 75
WETTED_FACTOR = 1.7  # Eq. 4-18, p. 75
FRICTION_FACTOR = 0.075  # Eq. 4-19, p. 75
FRICTION_LOG_OFFSET = 2  # Eq. 4-19
WATER_VISCOSITY_FT2_S = 1.2817e-5  # Table 4-1, p. 53: salt water, 15 C
PROPELLER_DRAG = 1.0  # Eq. 4-21, p. 76
PROPELLER_EXPANSION = 0.838  # Eq. 4-22, p. 76, pitch/diameter = 1
PROPELLER_AREA_RATIO = {"DDG": 100, "CG": 160, "CVN": 125, "LHD": 125}  # Table 4-7; LHD uses carrier analogy (estimate)
CURRENT_YAW = {"warship": (-0.201, 0.00221), "carrier": (-0.168, 0.00189)}  # Table 4-10, p. 79 (FFG / CVE 55)
# Figure 3-5, p. 37, synoptic curve: approximate graphical readings, NOT exact table entries.
SYNOPTIC_30S_OVER_HOURLY = 1.31
SYNOPTIC_60S_OVER_HOURLY = 1.25
SUSTAINED_TO_30S = SYNOPTIC_30S_OVER_HOURLY / SYNOPTIC_60S_OVER_HOURLY
# Engineering estimates/regularization below are NOT UFC prescriptions.
SUPERSTRUCTURE_LENGTH_FRACTION = 0.5  # rectangular profile estimate over half LWL
ESTIMATED_MIDSHIP_COEFFICIENT = 0.83  # analogy to Table 4-8 destroyer, p. 77
MIN_FRICTION_REYNOLDS = 10000.0  # numerical floor avoids Eq. 4-19 singularity at Re=100
AXIAL_COS_TOLERANCE = 1e-12  # floating-point beam-direction zero; not a physical coefficient
