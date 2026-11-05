"""Cross-field and cross-resource input checks that a Pydantic model alone cannot do (S00a).

Rules (documented in docs/CONTRACT_SEMANTICS.md):
- The request body is authoritative. `scenario_id` is a label for a saved scenario; when present it must exist and
  must not contradict the body on ship class, loading, berth or side. Disagreement is a 422 listing every conflict;
  nothing is resolved silently. Editing the line configuration against a saved scenario is allowed.
- Relative bearings in an environment snapshot duplicate information already in the true bearings plus the ship
  heading. If both are given they must agree (0.5 degrees); otherwise 422.
"""

from mooring import refdata, scenarios
from mooring.core.geometry import ship_heading_true
from mooring.core.schemas import AnalyzeRequest, EnvironmentSnapshot, LoadsRequest

BEARING_TOLERANCE_DEG = 0.5


def _circular_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def relative_bearing_conflicts(env: EnvironmentSnapshot, heading_true_deg: float) -> list[str]:
    conflicts = []
    for name, given, true_deg in (("wind_rel_ship_deg", env.wind_rel_ship_deg, env.wind_from_true_deg),
                                  ("current_rel_ship_deg", env.current_rel_ship_deg, env.current_set_true_deg)):
        if given is None:
            continue
        expected = (true_deg - heading_true_deg) % 360
        if _circular_diff(given, expected) > BEARING_TOLERANCE_DEG:
            conflicts.append(f"environment.{name}={given} disagrees with the true bearing and ship heading "
                             f"{heading_true_deg:.1f} (expected {expected:.1f}); send one or make them agree")
    return conflicts


def _raise(conflicts: list[str]) -> None:
    if conflicts:
        raise refdata.InvalidReference("Conflicting inputs: " + "; ".join(conflicts))


def check_analyze(req: AnalyzeRequest) -> None:
    """Validate duplicated inputs of any AnalyzeRequest (analyze, envelope, tide sweep, risk, hold plan)."""
    conflicts = []
    if req.scenario_id is not None:
        try:
            sc = scenarios.get(req.scenario_id)
        except refdata.NotFound:
            raise refdata.InvalidReference(f"scenario_id '{req.scenario_id}' does not exist") from None
        for field, body, saved in (("ship_class_id", req.ship_class_id, sc.ship_class_id),
                                   ("loading", req.loading, sc.loading), ("berth_id", req.berth_id, sc.berth_id),
                                   ("config.side_to", req.config.side_to, sc.side_to)):
            if body != saved:
                conflicts.append(f"{field}='{body}' conflicts with saved scenario '{req.scenario_id}' ('{saved}')")
    try:
        heading = ship_heading_true(refdata.berth(req.berth_id), req.config.side_to)
    except refdata.NotFound:
        heading = None  # the solver reports the unknown berth
    if heading is not None:
        conflicts += relative_bearing_conflicts(req.environment, heading)
    _raise(conflicts)


def check_loads(req: LoadsRequest) -> None:
    _raise(relative_bearing_conflicts(req.environment, req.heading_true_deg))
