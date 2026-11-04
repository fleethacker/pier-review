"""UFC load-model validity warnings, shared by every module that computes loads.

The /loads endpoints, the mooring analysis and the berthing tug plan all report the same findings, so a
depth/draft clamp or out-of-range current is never silently dropped downstream.
"""

from mooring.core.schemas import Finding
from mooring.core.units import KT_TO_FPS

from . import coefficients as c

DEPTH_RULE = "UFC-DEPTH-RANGE"
CURRENT_RULE = "UFC-CURRENT-SPEED"
REYNOLDS_RULE = "UFC-LOW-REYNOLDS"


def range_findings(depth_ft: float, draft_ft: float, current_speed_kt: float,
                   reynolds: list[float]) -> tuple[list[Finding], list[str]]:
    """Return (findings, assumption notes) for inputs outside the UFC load model's valid range."""
    findings: list[Finding] = []
    notes: list[str] = []
    if depth_ft <= draft_ft:
        message = ("Depth/draft clamped to 1.0 (T/d=1) for UFC Figure 4-9." if depth_ft < draft_ft
                   else "Depth equals draft (T/d=1); no under-keel clearance.")
        notes.append(message)
        findings.append(Finding(rule_id=DEPTH_RULE, severity="AMBER",
                                message=message + " Ground contact is outside this model.",
                                reference="UFC Figure 4-9; Eq. 4-10"))
    if current_speed_kt * KT_TO_FPS > c.CURRENT_LIMIT_FPS:
        findings.append(Finding(rule_id=CURRENT_RULE, severity="AMBER",
                                message="Current exceeds the 1.5 m/s range of the Seelig coefficient; results "
                                        "extrapolate without modeling heel or channel blockage.",
                                reference="UFC 4-5.1, pp. 72–73"))
    if any(0 < r < c.MIN_FRICTION_REYNOLDS for r in reynolds):
        message = (f"Friction Reynolds number floored at {c.MIN_FRICTION_REYNOLDS:g}; numerical regularization, "
                   "not a UFC low-speed prescription.")
        notes.append(message)
        findings.append(Finding(rule_id=REYNOLDS_RULE, severity="AMBER", message=message,
                                reference="UFC Eqs. 4-19/4-20"))
    return findings, notes
