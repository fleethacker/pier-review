"""Mock tug sizing (M6, shared by the moored and berthing phases).

Splits a required lateral force between the forward and aft push points on the water side and assigns the
smallest adequate tug to each. Workstream C replaces it with yaw-balanced placement and certified bollard pull.
"""

from mooring import refdata
from mooring.core.schemas import PushPointForce, ShipClass, TugAssignment, TugPlanResult


def size_tugs(ship: ShipClass, required: float, onto_pier: bool, side_to: str, heading: float,
              tug_ids: list[str] | None, rationale: list[str]) -> TugPlanResult:
    """Assign tugs to carry `required` lbf laterally. onto_pier=True means tugs must pull the ship off."""
    water_side = "port" if side_to == "starboard" else "starboard"
    pps = sorted([p for p in ship.push_points if p.side == water_side], key=lambda p: -p.x_ft)
    mode = "pull" if onto_pier else "push"
    per_point = required / max(len(pps), 1)
    fleet = sorted((refdata.tug(t) for t in tug_ids) if tug_ids else refdata.tugs(),
                   key=lambda t: -t.bollard_pull_ahead_lbf)
    # Push toward the pier = toward the pier-side beam; pull = away from it.
    toward_pier = (heading + (90 if side_to == "starboard" else 270)) % 360
    direction = toward_pier if mode == "push" else (toward_pier + 180) % 360

    def pull(t):
        return t.bollard_pull_ahead_lbf if mode == "push" else t.bollard_pull_astern_lbf

    assignments, total_bp, total_hp = [], 0.0, 0.0
    by_point = []
    for pp in pps:
        by_point.append(PushPointForce(push_point_id=pp.push_point_id, force_lbf=round(per_point), mode=mode))
        if required <= 0 or not fleet:
            continue
        # Smallest tug that covers this push point; otherwise the strongest one left.
        enough = [t for t in fleet if pull(t) >= per_point]
        tug = min(enough, key=pull) if enough else fleet[0]
        fleet.remove(tug)
        bp = pull(tug)
        assignments.append(TugAssignment(tug_id=tug.tug_id, push_point_id=pp.push_point_id, mode=mode,
                                         force_lbf=round(min(bp, per_point)), direction_true_deg=round(direction, 1)))
        total_bp += bp
        total_hp += tug.power_hp
    feasible = total_bp >= required
    if required > 0 and not feasible:
        rationale.append(f"Available tugs give {total_bp:,.0f} lbf; {required:,.0f} lbf needed.")
    return TugPlanResult(required_lateral_lbf=round(required), required_by_point=by_point, assignments=assignments,
                         total_bollard_pull_lbf=round(total_bp), total_power_hp=round(total_hp),
                         recommended_tug_count=len(assignments), feasible=feasible, rationale=rationale)
