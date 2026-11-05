import { describe, expect, it, vi } from 'vitest';

// Cesium needs WebGL and workers; the view controller only calls a handful of camera methods, so a stand-in is enough.
vi.mock('cesium', () => {
  class Frustum {
    width = 0;
  }
  return {
    OrthographicFrustum: Frustum,
    PerspectiveFrustum: class {},
    Matrix4: { IDENTITY: {} },
    Cartesian3: class {
      static add = () => ({});
      static multiplyByScalar = () => ({});
    },
    HeadingPitchRange: class {
      constructor(
        public heading: number,
        public pitch: number,
        public range: number,
      ) {}
    },
    Math: { toRadians: (d: number) => d },
  };
});

import { ViewController } from './viewController';

const bounds = { minX: 0, maxX: 400, minY: -50, maxY: 100 };

function fakeCamera() {
  return {
    frustum: new (class {})(),
    switchToOrthographicFrustum() {},
    switchToPerspectiveFrustum() {},
    lookAtTransform() {},
    setView() {},
    lookAt: vi.fn(),
  };
}

describe('ViewController intro', () => {
  it('eases in from a high steep view and ends on the framed one', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    const raf = vi.fn((cb: FrameRequestCallback) => setTimeout(() => cb(performance.now()), 16) as unknown as number);
    vi.stubGlobal('requestAnimationFrame', raf);
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
    const cam = fakeCamera();
    const frames = vi.fn();
    const v = new ViewController(cam as never, frames);
    v.setFrame({ frame: { xBearingTrueDeg: 90 }, toWorld: () => ({}), up: {} } as never);
    v.setMode('3d');
    v.playIntro();
    v.fit(bounds, 1.6);
    type Hpr = { heading: number; pitch: number; range: number };
    const first = cam.lookAt.mock.calls.at(-1)![1] as Hpr;
    await vi.advanceTimersByTimeAsync(3000);
    const last = cam.lookAt.mock.calls.at(-1)![1] as Hpr;
    expect(frames).toHaveBeenCalled();
    expect(first.range).toBeGreaterThan(last.range * 2); // starts far away...
    expect(first.pitch).toBeLessThan(last.pitch - 20); // ...and steep
    expect(last.pitch).toBeCloseTo(-34);
    expect(last.range).toBeCloseTo(400 * 0.9); // framed on the bounds
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('is cancelled by user input, so it never fights the user', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(performance.now()), 16) as unknown as number);
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id));
    const cam = fakeCamera();
    const v = new ViewController(cam as never);
    v.setFrame({ frame: { xBearingTrueDeg: 90 }, toWorld: () => ({}), up: {} } as never);
    v.setMode('3d');
    v.playIntro();
    v.fit(bounds, 1.6);
    await vi.advanceTimersByTimeAsync(100);
    v.zoomBy(0.5);
    const calls = cam.lookAt.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(cam.lookAt.mock.calls.length).toBe(calls); // no further intro frames after the zoom
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
