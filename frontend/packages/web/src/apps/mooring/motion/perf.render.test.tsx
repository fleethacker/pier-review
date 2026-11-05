// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene, Vec2 } from './frames';
import { MotionCanvas } from './MotionCanvas';
import { motionSceneParts } from './sceneMapper';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const base = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;

afterEach(cleanup);

/** A rich rm0-v1 frame: 30 lines with polylines, 3 tugs with positions and forces, roll/pitch and water present. */
function richFrame(i: number): SimFrame {
  const line = base.line_states![0];
  const tug = base.tug_states![0];
  return {
    ...base,
    t_s: i / 10,
    sequence: i,
    motion: {
      ...base.motion!,
      pose: { ...base.motion!.pose, x_ft: 300 + i * 0.05, heave_mllw_ft: 1 + Math.sin(i / 10), roll_deg: Math.sin(i / 7) * 3, pitch_deg: Math.cos(i / 9) },
      dofs: { ...base.motion!.dofs, heave: 'simulated', roll: 'simulated', pitch: 'simulated' },
    },
    line_states: Array.from({ length: 30 }, (_, k) => ({ ...line, line_number: k + 1, tension_lbf: 1000 + 400 * k + i })),
    tug_states: Array.from({ length: 3 }, (_, k) => ({ ...tug, tug_id: `tug-${k + 1}` })),
    lines: Array.from({ length: 30 }, (_, k) => ({ line_number: k + 1, tension_lbf: 1000 + 400 * k })),
  } as SimFrame;
}

describe('10 Hz motion path in jsdom', () => {
  it('adapts, maps and renders 100 rich frames (30 lines, 3 tugs) far inside the 100 ms frame period', () => {
    const N = 100;
    const frames = Array.from({ length: N }, (_, i) => richFrame(i));
    // Same trail the controller keeps: grows to 600 points.
    const trail: Vec2[] = [];
    const adaptMs: number[] = [];
    const mapMs: number[] = [];
    const renderMs: number[] = [];

    const first = adaptFrame(frames[0], { faceBearingDeg: scene.face_bearing_true_deg });
    const view = render(<MotionCanvas frame={first} scene={scene} trail={trail} faceBearingDeg={90} />);

    const total: number[] = [];
    for (let i = 0; i < N; i++) {
      const t0 = performance.now();
      const v = adaptFrame(frames[i], { faceBearingDeg: scene.face_bearing_true_deg });
      const t1 = performance.now();
      const parts = motionSceneParts(v, scene, null);
      const t2 = performance.now();
      trail.push({ x: v.ship.x_ft, y: v.ship.y_ft });
      view.rerender(<MotionCanvas frame={v} scene={scene} trail={[...trail]} faceBearingDeg={90} />);
      const t3 = performance.now();
      expect(parts.entities.some((e) => e.id === 'motion-water')).toBe(true);
      adaptMs.push(t1 - t0);
      mapMs.push(t2 - t1);
      renderMs.push(t3 - t2);
      total.push(t3 - t0);
    }
    const stat = (a: number[]) => {
      const s = [...a].sort((x, y) => x - y);
      return { mean: a.reduce((x, y) => x + y, 0) / a.length, median: s[Math.floor(s.length / 2)], p95: s[Math.floor(s.length * 0.95)], max: s[s.length - 1] };
    };
    const f = (x: number) => x.toFixed(2);
    const r = { adapt: stat(adaptMs), map: stat(mapMs), render: stat(renderMs), total: stat(total) };
    console.info(`10 Hz profile (ms/frame, jsdom): ${Object.entries(r).map(([k, v]) => `${k} mean ${f(v.mean)} median ${f(v.median)} p95 ${f(v.p95)} max ${f(v.max)}`).join(' | ')}`);

    // The period is 100 ms and a real browser lays out and paints on top of this. Alone this measures about 4 ms per
    // frame; the full suite runs ~30 jsdom workers in parallel, so the gate uses the median (robust to a starved
    // worker or a GC pause) at 40 ms and the mean at the whole period.
    expect(r.total.median).toBeLessThan(40);
    expect(r.total.mean).toBeLessThan(100);
    // The SVG really holds the lines and tugs it was given.
    expect(view.container.querySelectorAll('line, polyline, path').length).toBeGreaterThan(30);
  });
});
