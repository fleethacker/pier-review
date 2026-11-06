import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Vec2, ViewFrame } from './frames';

/** Presentation latency only. No velocity integration or extrapolation beyond received states. */
export const DISPLAY_DELAY_MS = 120;
export const MAX_INTERPOLATION_GAP_MS = 250;
type Pose = { x: number; y: number; yaw: number };
const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
export const angleBetween = (a: number, b: number, f: number) => ((a + ((((b - a + 180) % 360 + 360) % 360) - 180) * f) % 360 + 360) % 360;
const point = (a: Vec2 | null, b: Vec2 | null, f: number): Vec2 | null => a && b ? { x: lerp(a.x, b.x, f), y: lerp(a.y, b.y, f) } : b;
const shipPose = (f: ViewFrame): Pose => ({ x: f.ship.x_ft, y: f.ship.y_ft, yaw: f.ship.yawDeg });
const rotate = (p: Vec2, degrees: number): Vec2 => {
  const a = degrees * Math.PI / 180;
  return { x: p.x * Math.cos(a) - p.y * Math.sin(a), y: p.x * Math.sin(a) + p.y * Math.cos(a) };
};
/** Keep supplied attachment points on the interpolated hull, including shortest-angle turns. */
function attached(a: Vec2 | null, b: Vec2 | null, from: Pose, to: Pose, drawn: Pose, f: number): Vec2 | null {
  if (!b) return null;
  const localB = rotate({ x: b.x - to.x, y: b.y - to.y }, -to.yaw);
  const localA = a ? rotate({ x: a.x - from.x, y: a.y - from.y }, -from.yaw) : localB;
  const local = rotate(point(localA, localB, f)!, drawn.yaw);
  return { x: local.x + drawn.x, y: local.y + drawn.y };
}

/** Only geometry is interpolated. Safety, clock, velocities, forces and availability remain the latest evidence. */
export function interpolateGeometry(a: ViewFrame, b: ViewFrame, latest: ViewFrame, fraction: number): ViewFrame {
  const f = Math.max(0, Math.min(1, fraction));
  const from = shipPose(a), to = shipPose(b);
  const drawn = { x: lerp(from.x, to.x, f), y: lerp(from.y, to.y, f), yaw: angleBetween(from.yaw, to.yaw, f) };
  const shipPoint = (p: Vec2 | null, q: Vec2 | null) => attached(p, q, from, to, drawn, f);
  const tugs = latest.tugs.map((t) => {
    const before = a.tugs.find((p) => p.id === t.id), after = b.tugs.find((p) => p.id === t.id);
    if (!before || !after || !t.position || t.badge?.validity === 'invalid') return t;
    return { ...t, position: point(before.position, after.position, f),
      headingTrueDeg: before.headingTrueDeg != null && after.headingTrueDeg != null ? angleBetween(before.headingTrueDeg, after.headingTrueDeg, f) : t.headingTrueDeg,
      applicationPoint: t.applicationPoint ? shipPoint(before.applicationPoint, after.applicationPoint) : null };
  });
  return { ...latest,
    ship: { ...latest.ship, x_ft: drawn.x, y_ft: drawn.y, yawDeg: drawn.yaw, headingTrueDeg: angleBetween(a.ship.headingTrueDeg, b.ship.headingTrueDeg, f) },
    tugs,
    lines: latest.lines.map((line) => {
      const before = a.lines.find((p) => p.lineNumber === line.lineNumber), after = b.lines.find((p) => p.lineNumber === line.lineNumber);
      if (!before || !after || !line.shipEnd) return line;
      const shipEnd = shipPoint(before.shipEnd, after.shipEnd);
      const polyline = before.polyline && after.polyline && before.polyline.length === after.polyline.length
        ? after.polyline.map((p, i) => point(before.polyline![i], p, f)!) : line.polyline?.map((p) => ({ ...p })) ?? null;
      if (polyline?.length && shipEnd && after.shipEnd) {
        // Preserve whichever end of the supplied polyline is the hull attachment.
        if (Math.hypot(polyline[0].x - after.shipEnd.x, polyline[0].y - after.shipEnd.y) < Math.hypot(polyline.at(-1)!.x - after.shipEnd.x, polyline.at(-1)!.y - after.shipEnd.y)) polyline[0] = shipEnd;
        else polyline[polyline.length - 1] = shipEnd;
      }
      return { ...line, shipEnd, polyline };
    }),
    controls: latest.controls ? { ...latest.controls, actuators: latest.controls.actuators?.map((actuator) => {
      const before = a.controls?.actuators?.find((p) => p.actuator_id === actuator.actuator_id), after = b.controls?.actuators?.find((p) => p.actuator_id === actuator.actuator_id);
      if (!before || !after) return actuator;
      const p = shipPoint({ x: before.x_ft, y: before.y_ft }, { x: after.x_ft, y: after.y_ft })!;
      return { ...actuator, x_ft: p.x, y_ft: p.y };
    }) } : null,
    tugDynamics: latest.tugDynamics.map((state) => {
      const before = a.tugDynamics.find((p) => p.tug_id === state.tug_id), after = b.tugDynamics.find((p) => p.tug_id === state.tug_id);
      if (!before || !after) return state;
      const shipEnd = shipPoint({ x: before.ship_point_x_ft, y: before.ship_point_y_ft }, { x: after.ship_point_x_ft, y: after.ship_point_y_ft })!;
      const tugBefore = a.tugs.find((p) => p.id === state.tug_id), tugAfter = b.tugs.find((p) => p.id === state.tug_id), tugDrawn = tugs.find((p) => p.id === state.tug_id);
      const tugEnd = tugBefore?.position && tugAfter?.position && tugDrawn?.position && tugBefore.headingTrueDeg != null && tugAfter.headingTrueDeg != null && tugDrawn.headingTrueDeg != null
        ? attached({ x: before.tug_point_x_ft, y: before.tug_point_y_ft }, { x: after.tug_point_x_ft, y: after.tug_point_y_ft }, { ...tugBefore.position, yaw: -tugBefore.headingTrueDeg }, { ...tugAfter.position, yaw: -tugAfter.headingTrueDeg }, { ...tugDrawn.position, yaw: -tugDrawn.headingTrueDeg }, f)!
        : { x: state.tug_point_x_ft, y: state.tug_point_y_ft };
      return { ...state, ship_point_x_ft: shipEnd.x, ship_point_y_ft: shipEnd.y, tug_point_x_ft: tugEnd.x, tug_point_y_ft: tugEnd.y };
    }),
  };
}

export class MotionDisplayBuffer {
  private samples: { frame: ViewFrame; receivedAt: number }[] = [];
  push(frame: ViewFrame, receivedAt: number, active: boolean): void {
    const previous = this.samples.at(-1);
    const usable = (f: ViewFrame) => f.badge.validity === 'valid' || f.badge.validity === 'limited';
    if (!active || !usable(frame) || !previous || !usable(previous.frame) || frame.runId !== previous.frame.runId || frame.sceneId !== previous.frame.sceneId || frame.sceneRevision !== previous.frame.sceneRevision || frame.sessionId !== previous.frame.sessionId || frame.tS <= previous.frame.tS || receivedAt <= previous.receivedAt || receivedAt - previous.receivedAt > MAX_INTERPOLATION_GAP_MS) this.samples = [];
    this.samples.push({ frame, receivedAt });
    this.samples = this.samples.slice(-8);
  }
  sample(latest: ViewFrame, now: number): ViewFrame {
    if (this.samples.at(-1)?.frame !== latest || this.samples.length < 2) return latest;
    const target = now - DISPLAY_DELAY_MS;
    for (let i = 1; i < this.samples.length; i++) {
      const a = this.samples[i - 1], b = this.samples[i];
      if (target <= b.receivedAt) return interpolateGeometry(a.frame, b.frame, latest, (target - a.receivedAt) / (b.receivedAt - a.receivedAt));
    }
    return latest; // Stream gap: hold the latest received geometry. Never extrapolate.
  }
}

export function useMotionDisplayFrame(frame: ViewFrame | null, active: boolean): ViewFrame | null {
  const buffer = useRef(new MotionDisplayBuffer());
  const [now, setNow] = useState(0);
  useLayoutEffect(() => {
    if (frame) buffer.current.push(frame, performance.now(), active);
    setNow(performance.now());
  }, [frame, active]);
  useEffect(() => {
    if (!active || !frame) return;
    let id = 0;
    const until = performance.now() + DISPLAY_DELAY_MS + 20;
    const tick = (time: number) => { setNow(time); if (time < until) id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [frame, active]);
  return frame && active ? buffer.current.sample(frame, now) : frame;
}
