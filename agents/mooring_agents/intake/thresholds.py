"""Intake policy thresholds. Values deliberately preserve the existing detector.

NSTM limits are shared reference data, not an imported physics implementation.
Local warning policies must not be presented as numeric requirements from NSTM.
"""
from mooring.rules.nstm582 import MST_LIMITS  # NSTM Table 582-1-1 (single canonical MST table)

WIND_AMBER_KT = float(MST_LIMITS["I"][0][0])  # NSTM Table 582-1-1: MST I sustained wind
WIND_RED_KT = float(MST_LIMITS["II"][0][0])  # NSTM Table 582-1-1: MST II sustained wind
CURRENT_AMBER_KT = MST_LIMITS["I"][0][1]  # NSTM Table 582-1-1: MST I current
CURRENT_RED_KT = MST_LIMITS["II"][0][1]  # NSTM Table 582-1-1: MST II current
GUST_RED_KT = WIND_AMBER_KT  # Local early-warning policy using MST I value; not an NSTM gust limit
GUST_AMBER_KT = 25.0  # Local warning policy; no NSTM numerical requirement claimed
SHIFT_DEG_PER_HOUR = 45.0  # Local shift-warning policy; no NSTM numerical requirement claimed
STALE_S = 900  # Local data-freshness policy; not an NSTM limit
BERTHING_MAX_CURRENT_KT = 0.5  # Existing local berthing-window policy, not an NSTM limit
FORECAST_STEP_MIN = 30  # Existing sampling cadence, not an NSTM threshold
MIN_SHIFT_INTERVAL_HOURS = 1e-6  # Existing numeric guard for coincident timestamps
