"""Self-contained SVG presentation of saved assessed geometry; no new physics or catalog access."""

import html
import math

from mooring.core.envelopes import resolved_inputs_hash
from mooring.core.geometry import standoff_ft
from mooring.mechanics.pose import Pose, ShipFrame

from .schemas import SheetLayout


def sheet_binding_hash(sheet) -> str:
    """Detect a document edited without rebuilding its associated graphic."""
    return resolved_inputs_hash({"sheet_id": sheet.sheet_id, "version": sheet.version, "plan_id": sheet.plan_id,
        "review_id": sheet.review_id, "analysis_result_id": sheet.analysis_result_id,
        "status": sheet.status, "validity": sheet.validity.model_dump(mode="json") if sheet.validity else None,
        "header": sheet.header.model_dump(mode="json"), "environment": sheet.environment.observed.model_dump(mode="json"),
        "lines": [line.model_dump(mode="json") for line in sheet.line_plan],
        "holding_tugs": [t.model_dump(mode="json") for t in sheet.holding_tugs or []],
        "berthing_tugs": sheet.tug_plan.model_dump(mode="json") if sheet.tug_plan else None})


def build_layout(rec, sheet, review=None) -> SheetLayout:
    snapshot = getattr(rec, "geometry_snapshot", None)
    identity = dict(sheet_id=sheet.sheet_id, sheet_version=sheet.version, plan_id=sheet.plan_id,
                    review_id=sheet.review_id, analysis_result_id=sheet.analysis_result_id)
    def unavailable(reason):
        return SheetLayout(**identity, state="unavailable", unavailable_reason=reason)
    if snapshot is None:
        return unavailable("No geometry was captured with this plan; a current map cannot establish its assessed layout.")
    if snapshot.unavailable_reason:
        return unavailable(snapshot.unavailable_reason)
    if review is not None and getattr(review, "plan_id", None) != sheet.plan_id:
        return unavailable("The independent review belongs to a different plan.")
    if review is not None and getattr(review, "geometry_snapshot_verified", None) is not True:
        return unavailable("The independent review has not verified the captured geometry reference revisions.")
    if snapshot.analysis_result_id != sheet.analysis_result_id:
        return unavailable("Captured geometry belongs to a different analysis result.")
    if (resolved_inputs_hash(snapshot.ship) != snapshot.ship_revision or
            resolved_inputs_hash(snapshot.berth) != snapshot.berth_revision):
        return unavailable("Captured reference geometry changed after assessment.")
    if sheet.validity is None or sheet.validity.state not in ("valid", "limited"):
        return unavailable("Assessment validity does not establish a usable solved layout.")
    ship, berth, cfg = snapshot.ship, snapshot.berth, snapshot.config
    if rec.plan.config is None or ship.class_id != sheet.header.ship_class_id or berth.berth_id != sheet.header.berth_id:
        return unavailable("Captured geometry does not match the sheet ship, berth or configuration.")
    if (resolved_inputs_hash(cfg) != resolved_inputs_hash(rec.plan.config) or
            resolved_inputs_hash(snapshot.environment) != resolved_inputs_hash(sheet.environment.observed) or
            snapshot.offset != rec.analysis.result.offset):
        return unavailable("Plan configuration or assessed conditions changed after geometry capture.")
    try:
        svg = _svg(ship, berth, cfg, snapshot.offset, sheet)
    except (KeyError, ValueError, OverflowError) as exc:
        return unavailable(f"Layout geometry is incomplete or invalid: {exc}")
    digest = resolved_inputs_hash({"references": snapshot.model_dump(mode="json"),
        "config": cfg.model_dump(mode="json"), "offset": rec.analysis.result.offset.model_dump(mode="json"),
        "environment": sheet.environment.observed.model_dump(mode="json"),
        "holding_tugs": [t.model_dump(mode="json") for t in sheet.holding_tugs or []],
        "berthing_tugs": sheet.tug_plan.model_dump(mode="json") if sheet.tug_plan else None})
    return SheetLayout(**identity, state="available", svg=svg, geometry_hash=digest,
                       sheet_binding_hash=sheet_binding_hash(sheet),
                       ship_revision=snapshot.ship_revision, berth_revision=snapshot.berth_revision)


def _svg(ship, berth, cfg, offset, sheet):
    e = html.escape
    frame = ShipFrame(cfg.side_to, cfg.ship_x_ft, standoff_ft(berth, cfg) + ship.beam_ft / 2)
    # Result surge is ship-forward; mechanics.Pose dx is berth-frame along-pier.
    pose = Pose(offset.surge_ft * (1 if cfg.side_to == "starboard" else -1),
                offset.sway_ft, math.radians(offset.yaw_deg))
    def at(x, y):
        point = frame.to_berth(x, y, pose)
        if not all(math.isfinite(v) for v in point):
            raise ValueError("nonfinite coordinate")
        return point
    ship_fittings = {f.fitting_id: f for f in ship.fittings}
    pier_fittings = {f.fitting_id: f for f in berth.fittings}
    if len(ship_fittings) != len(ship.fittings):
        raise ValueError("duplicate ship fitting IDs")
    hull = [at(-ship.loa_ft / 2, -ship.beam_ft / 2), at(ship.loa_ft * .35, -ship.beam_ft / 2),
            at(ship.loa_ft / 2, 0), at(ship.loa_ft * .35, ship.beam_ft / 2), at(-ship.loa_ft / 2, ship.beam_ft / 2)]
    connections = []
    for line in cfg.lines:
        bitt = ship_fittings[line.ship_fitting_id]
        lead_id = line.chock_id or bitt.paired_chock_id
        lead = ship_fittings[lead_id] if lead_id else bitt
        pier = pier_fittings[line.pier_fitting_id]
        connections.append((line, at(lead.x_ft, lead.y_ft), (pier.x_ft, pier.y_ft), lead.fitting_id))
    points = [*hull, (0, 0), (berth.face_length_ft, 0), *[(f.x_ft, f.y_ft) for f in berth.fittings]]
    if not all(math.isfinite(v) for point in points for v in point):
        raise ValueError("nonfinite coordinate")
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] for p in points) - 30, max(p[1] for p in points) + 80
    scale = min(880 / max(xmax - xmin, 1), 270 / max(ymax - ymin, 1))
    def xy(point):
        return (45 + (point[0] - xmin) * scale, 65 + (ymax - point[1]) * scale)
    def text(x, y, value, size=11):
        return f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}">{e(str(value))}</text>'
    def segment(a, b, color="#334155", width=2):
        return f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{color}" stroke-width="{width}"/>'
    legend_y = max(220, 65 + (ymax - ymin) * scale + 30)
    legend_rows = (len(connections) + 1) // 2
    env_y = legend_y + legend_rows * 32 + 28
    height = env_y + 95
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 {height:.2f}" role="img" aria-label="Assessed mooring layout">',
           f'<rect width="1000" height="{height:.2f}" fill="white"/>', '<g font-family="sans-serif" fill="#172554">',
           text(20, 22, f"{ship.class_id} · {berth.berth_id} · {cfg.side_to} side to", 15),
           text(20, 42, f"Solved plan view; schematic hull. Assessment validity: {sheet.validity.state}."),
           '<polygon points="' + ' '.join(f'{x:.2f},{y:.2f}' for x, y in map(xy, hull)) + '" fill="#dbeafe" stroke="#1e40af"/>',
           segment(xy((0, 0)), xy((berth.face_length_ft, 0)), "#475569", 6)]
    for index, (line, ship_end, pier_end, lead_id) in enumerate(connections):
        a, b = xy(ship_end), xy(pier_end)
        legend_x = 20 + (index // max(legend_rows, 1)) * 490
        row_y = legend_y + (index % max(legend_rows, 1)) * 32
        out += [segment(a, b, "#2563eb"), text((a[0] + b[0])/2, (a[1] + b[1])/2 - 4, f"#{line.line_number}", 11),
                text(legend_x, row_y, f"#{line.line_number} · {line.spec_id} · {line.parts} part(s)", 12),
                text(legend_x, row_y + 14, f"{line.ship_fitting_id} → {lead_id} → {line.pier_fitting_id}", 11)]
    used = {line.pier_fitting_id for line, *_ in connections}
    for identifier in sorted(used):
        fitting = pier_fittings[identifier]
        x, y = xy((fitting.x_ft, fitting.y_ft))
        out += [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#475569"/>', text(x - 10, y + 15, identifier, 9)]
    pushes = {p.push_point_id: p for p in ship.push_points}
    for label, assignments in (("Holding", sheet.holding_tugs or []), ("Berthing", sheet.tug_plan.assignments if sheet.tug_plan else [])):
        for index, tug in enumerate(assignments):
            point = pushes[tug.push_point_id]
            x, y = xy(at(point.x_ft, ship.beam_ft / 2 * (1 if point.side == "port" else -1)))
            out += [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="none" stroke="#92400e"/>',
                    text(x + 7, y - 8 - index * 11, f"{label} {tug.tug_id} ({tug.mode})", 10)]
    # Compass and environment arrows encode direction only; lengths are not force/speed magnitudes.
    env = sheet.environment.observed
    for index, (label, bearing) in enumerate((("North", 0), ("Wind toward", (env.wind_from_true_deg + 180) % 360),
                                             ("Current toward", env.current_set_true_deg))):
        angle = math.radians(berth.face_bearing_true_deg - bearing)
        a = (70 + index * 245, env_y)
        b = (a[0] + 27 * math.cos(angle), a[1] - 27 * math.sin(angle))
        back = (b[0] - 7 * math.cos(angle), b[1] + 7 * math.sin(angle))
        out += [segment(a, b), segment(b, (back[0] - 4 * math.sin(angle), back[1] - 4 * math.cos(angle))),
                segment(b, (back[0] + 4 * math.sin(angle), back[1] + 4 * math.cos(angle))), text(a[0] + 40, a[1] + 4, f"{label} {bearing:g}° true")]
    scale_ft = min(100, 150 / scale)
    out += [segment((800, env_y), (800 + scale_ft * scale, env_y)), text(800, env_y + 20, f"{scale_ft:g} ft scale"),
            text(20, env_y + 50, f"Sheet {sheet.sheet_id} v{sheet.version} · Plan {sheet.plan_id}"),
            text(20, env_y + 70, f"Review {sheet.review_id or 'not recorded'} · Analysis {sheet.analysis_result_id}"), '</g></svg>']
    return ''.join(out)
