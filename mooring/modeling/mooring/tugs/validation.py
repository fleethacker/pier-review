"""Catalog constraints for explicit holding assignments; no capacity inferred from horsepower."""
from mooring.core.schemas import ShipClass, TugAssignment, TugSpec


def assignment_errors(ship: ShipClass, assignments: list[TugAssignment], fleet: list[TugSpec]) -> list[str]:
    points = {p.push_point_id: p for p in ship.push_points}
    tugs = {t.tug_id: t for t in fleet}
    seen_tugs, seen_points, errors = set(), set(), []
    for a in assignments:
        if a.tug_id in seen_tugs or a.push_point_id in seen_points:
            errors.append('Each tug and push point may appear only once')
        seen_tugs.add(a.tug_id)
        seen_points.add(a.push_point_id)
        if a.tug_id not in tugs or a.push_point_id not in points:
            errors.append(f'Unknown tug or push point: {a.tug_id}/{a.push_point_id}')
            continue
        tug, point = tugs[a.tug_id], points[a.push_point_id]
        rating = tug.bollard_pull_ahead_lbf if a.mode == 'push' else tug.bollard_pull_astern_lbf
        if a.mode == 'standby':
            rating = 0
        if a.force_lbf > min(rating, point.max_force_lbf):
            errors.append(f'{a.tug_id}/{a.push_point_id}: force exceeds {a.mode} catalog or push-point rating')
    return errors
