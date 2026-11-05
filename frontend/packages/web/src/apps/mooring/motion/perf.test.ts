import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { motionSceneParts } from './sceneMapper';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const base = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;

/** The planning target: 10 Hz with 30 lines and 3 tugs must leave the main thread nearly idle. */
function bigFrame(): SimFrame {
  const line = base.line_states![0];
  const tug = base.tug_states![0];
  return {
    ...base,
    line_states: Array.from({ length: 30 }, (_, i) => ({ ...line, line_number: i + 1, tension_lbf: 1000 + 400 * i })),
    tug_states: Array.from({ length: 3 }, (_, i) => ({ ...tug, tug_id: `tug-${i + 1}` })),
    lines: Array.from({ length: 30 }, (_, i) => ({ line_number: i + 1, tension_lbf: 1000 + 400 * i })),
  };
}

describe('large frames', () => {
  it('adapts and maps 30 lines and 3 tugs well inside a 10 Hz frame budget', () => {
    const f = bigFrame();
    const N = 500;
    const t0 = performance.now();
    for (let i = 0; i < N; i++) {
      const v = adaptFrame({ ...f, t_s: i / 10, sequence: i }, { faceBearingDeg: 90 });
      motionSceneParts(v, scene, null);
    }
    const perFrameMs = (performance.now() - t0) / N;
    // The budget at 10 Hz is 100 ms; this work should use a tiny fraction of one frame.
    expect(perFrameMs).toBeLessThan(5);
  });
});
