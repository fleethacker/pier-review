import { describe, expect, it } from 'vitest';
import { distanceM, stationFrom } from './geo';
import { PRESET_SCENARIOS, blankScenario } from './scenarios';
import { buildFrameData, buildStaticData, DEFAULT_VIEW, groupStates, shipPoint } from './scene';
import { SHIP_CLASSES, shipShape } from './ships';
import { runScenario, statesAt, validateScenario } from './sim';

describe('preset scenarios', () => {
  for (const preset of [...PRESET_SCENARIOS, blankScenario()]) {
    describe(preset.name, () => {
      it('validates and runs to the end with finite numbers', () => {
        expect(validateScenario(preset)).toEqual([]);
        const t = runScenario(preset);
        expect(t.data.every(Number.isFinite)).toBe(true);
        const end = statesAt(t, preset.durationS);
        end.forEach((s, i) => {
          expect(s.speedKt).toBeLessThanOrEqual(SHIP_CLASSES[preset.units[i].classId].maxSpeedKt + 1e-9);
        });
      });
    });
  }

  it('keeps every escort near its station through the whole run, turns included', () => {
    for (const preset of PRESET_SCENARIOS) {
      const t = runScenario(preset);
      let worst = 0;
      for (let at = 0; at <= preset.durationS; at += 20) {
        const states = statesAt(t, at);
        preset.units.forEach((u, i) => {
          if (u.behavior.type !== 'escort') return;
          const b = u.behavior;
          const leader = states[preset.units.findIndex((l) => l.id === b.leaderId)];
          const station = stationFrom(leader, leader.headingDeg, b.aheadM, b.abeamM);
          worst = Math.max(worst, distanceM(states[i], station));
        });
      }
      expect(worst, preset.id).toBeLessThan(400);
    }
  });

  it('has the red craft in the encounter reach the destroyers before the run ends', () => {
    const preset = PRESET_SCENARIOS.find((p) => p.id === 'surface-encounter')!;
    const t = runScenario(preset);
    let closest = Infinity;
    for (let at = 0; at <= preset.durationS; at += 30) {
      const s = statesAt(t, at);
      const ddg = s[preset.units.findIndex((u) => u.id === 'ddg1')];
      const fac = s[preset.units.findIndex((u) => u.id === 'fac1')];
      closest = Math.min(closest, distanceM(ddg, fac));
    }
    expect(closest).toBeLessThan(5000);
  });
});

describe('ship shapes', () => {
  it('sizes the hull to the class and points the bow forward', () => {
    for (const id of Object.keys(SHIP_CLASSES) as (keyof typeof SHIP_CLASSES)[]) {
      const cls = SHIP_CLASSES[id];
      const { hull } = shipShape(id);
      const xs = hull.map((p) => p[0]);
      const ys = hull.map((p) => p[1]);
      expect(Math.max(...xs)).toBeCloseTo(cls.loaM / 2, 6);
      expect(Math.min(...xs)).toBeCloseTo(-cls.loaM / 2, 6);
      expect(Math.max(...ys)).toBeCloseTo(cls.beamM / 2, 6);
      expect(Math.min(...ys)).toBeCloseTo(-cls.beamM / 2, 6);
      expect(hull.find((p) => p[0] === cls.loaM / 2)![1]).toBe(0);
    }
  });

  it('keeps every part inside the hull length and above the deck', () => {
    for (const id of Object.keys(SHIP_CLASSES) as (keyof typeof SHIP_CLASSES)[]) {
      const cls = SHIP_CLASSES[id];
      for (const part of shipShape(id).parts) {
        expect(part.base).toBeGreaterThanOrEqual(cls.freeboardM);
        expect(part.height).toBeGreaterThan(part.base);
        for (const [x] of part.points) expect(Math.abs(x)).toBeLessThanOrEqual(cls.loaM / 2);
      }
    }
  });

  it('puts the bow at the heading and port to the left of it', () => {
    const at = { lon: -62, lat: 33 };
    const bowEast = shipPoint(at, 90, 100, 0);
    expect(bowEast[0]).toBeGreaterThan(at.lon);
    expect(bowEast[1]).toBeCloseTo(at.lat, 6);
    // Heading east, port (+y) is north.
    expect(shipPoint(at, 90, 0, 50)[1]).toBeGreaterThan(at.lat);
    expect(shipPoint(at, 0, 0, 50)[0]).toBeLessThan(at.lon);
  });
});

describe('frame data', () => {
  const preset = PRESET_SCENARIOS[0];
  const t = runScenario(preset);

  it('draws a hull, parts, halo and marker for each unit', () => {
    const f = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    expect(f.hulls.features).toHaveLength(preset.units.length * 3);
    expect(f.halos.features).toHaveLength(preset.units.length);
    expect(f.foam.features).toHaveLength(preset.units.length);
    expect(f.markers.features).toHaveLength(preset.units.length);
    expect(f.parts.features.length).toBeGreaterThan(preset.units.length);
    for (const h of f.hulls.features) {
      const ring = h.geometry.coordinates[0];
      expect(ring[0]).toEqual(ring[ring.length - 1]);
    }
  });

  it('stacks hull slices from the waterline up to the freeboard, widening toward the deck', () => {
    for (const id of Object.keys(SHIP_CLASSES) as (keyof typeof SHIP_CLASSES)[]) {
      const { slices } = shipShape(id);
      expect(slices[0].base).toBe(0);
      slices.slice(1).forEach((sl, i) => expect(sl.base).toBe(slices[i].top));
      expect(slices.at(-1)!.top).toBe(SHIP_CLASSES[id].freeboardM);
      expect(slices.at(-1)!.beamScale).toBeGreaterThan(slices[1].beamScale);
    }
  });

  it('gives every ship navigation lights, and big ships deck lights as well', () => {
    for (const id of Object.keys(SHIP_CLASSES) as (keyof typeof SHIP_CLASSES)[]) {
      const { lights } = shipShape(id);
      const colors = lights.map((l) => l.color);
      expect(colors).toContain('#ff3b30');
      expect(colors).toContain('#2bff72');
      const port = lights.find((l) => l.color === '#ff3b30')!;
      const starboard = lights.find((l) => l.color === '#2bff72')!;
      expect(port.y).toBeGreaterThan(0);
      expect(starboard.y).toBeLessThan(0);
      expect(lights.length > 4).toBe(SHIP_CLASSES[id].loaM >= 200);
    }
  });

  it('rotates angled parts, and keeps parts inside the ship even when rotated', () => {
    const { parts } = shipShape('CVN');
    const tilted = parts.filter((p) => p.points[0][0] !== p.points[3][0]);
    expect(tilted.length).toBeGreaterThan(3);
    expect(shipShape('DDG').parts.every((p) => p.points[0][0] === p.points[3][0])).toBe(true);
  });

  it('scales hulls and their heights together', () => {
    const one = buildFrameData(preset, t, 600, { ...DEFAULT_VIEW, shipScale: 1 }, null);
    const five = buildFrameData(preset, t, 600, { ...DEFAULT_VIEW, shipScale: 5 }, null);
    expect(five.hulls.features[0].properties.height).toBe(Number(one.hulls.features[0].properties.height) * 5);
    const extent = (f: typeof one) => {
      const r = f.hulls.features[0].geometry.coordinates[0];
      return distanceM({ lon: r[0][0], lat: r[0][1] }, { lon: r[4][0], lat: r[4][1] });
    };
    expect(extent(five) / extent(one)).toBeCloseTo(5, 1);
  });

  it('draws trails only for moving units and only when asked', () => {
    const on = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    expect(on.trails.features.length).toBeGreaterThan(0);
    for (const line of on.trails.features) expect(line.geometry.coordinates.length).toBeGreaterThanOrEqual(2);
    expect(buildFrameData(preset, t, 600, { ...DEFAULT_VIEW, trailS: 0 }, null).trails.features).toHaveLength(0);
    expect(buildFrameData(preset, t, 0, DEFAULT_VIEW, null).trails.features.length).toBeLessThanOrEqual(on.trails.features.length);
  });

  it('foams more at speed, and draws a light pillar and a glow point for each light', () => {
    const f = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    const foamOf = (id: string) => Number(f.foam.features.find((x) => x.properties.id === id)!.properties.foam);
    expect(foamOf('cvn1')).toBe(1);
    expect(foamOf('mv1')).toBeCloseTo(15 / 18, 2);
    const held = buildFrameData({ ...preset, units: preset.units.map((u) => (u.id === 'mv1' ? { ...u, speedKt: 0, behavior: { type: 'hold' as const } } : u)) }, runScenario({ ...preset, units: preset.units.map((u) => (u.id === 'mv1' ? { ...u, speedKt: 0, behavior: { type: 'hold' as const } } : u)) }), 600, DEFAULT_VIEW, null);
    expect(Number(held.foam.features.find((x) => x.properties.id === 'mv1')!.properties.foam)).toBeLessThan(0.1);
    const lightCount = preset.units.reduce((n, u) => n + shipShape(u.classId).lights.length, 0);
    expect(f.lights.features).toHaveLength(lightCount);
    expect(f.glows.features).toHaveLength(lightCount);
    for (const l of f.lights.features) expect(Number(l.properties.height)).toBeGreaterThan(Number(l.properties.base));
  });

  it('labels each ship with its speed and heading', () => {
    const f = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    const carrier = f.markers.features.find((m) => m.properties.id === 'cvn1')!;
    expect(carrier.properties.info).toMatch(/^18 kt\s+09\d°$/);
  });

  it('draws a V wake: a center trail and two arms that open up behind the ship', () => {
    const f = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    const mine = f.trails.features.filter((x) => x.properties.id === 'cvn1');
    expect(mine).toHaveLength(3);
    const [center, left, right] = mine.map((x) => x.geometry.coordinates);
    expect(left).toHaveLength(center.length);
    const gap = (k: number) => distanceM({ lon: left[k][0], lat: left[k][1] }, { lon: right[k][0], lat: right[k][1] });
    expect(gap(center.length - 1)).toBeGreaterThan(gap(0) * 2);
    for (let k = 1; k < center.length; k++) {
      const dl = distanceM({ lon: left[k][0], lat: left[k][1] }, { lon: center[k][0], lat: center[k][1] });
      const dr = distanceM({ lon: right[k][0], lat: right[k][1] }, { lon: center[k][0], lat: center[k][1] });
      expect(Math.abs(dl - dr)).toBeLessThan(dl * 0.05);
    }
  });

  it('adds a selection ring and, on request, a sensor ring for the selected unit only', () => {
    const none = buildFrameData(preset, t, 600, DEFAULT_VIEW, null);
    expect(none.overlays.features).toHaveLength(0);
    const sel = buildFrameData(preset, t, 600, DEFAULT_VIEW, 'cvn1');
    expect(sel.overlays.features.map((f) => f.properties.kind)).toEqual(['selection']);
    const range = buildFrameData(preset, t, 600, { ...DEFAULT_VIEW, showRange: true }, 'cvn1');
    expect(range.overlays.features.map((f) => f.properties.kind)).toEqual(['selection', 'range']);
    expect(range.halos.features.find((f) => f.properties.id === 'cvn1')!.properties.selected).toBe(true);
  });

  it('draws routes and numbered waypoints for route units, and none when hidden', () => {
    const s = buildStaticData(preset, DEFAULT_VIEW, 'cvn1');
    const routed = preset.units.filter((u) => u.behavior.type === 'route');
    expect(s.routes.features).toHaveLength(routed.length);
    const cvnPoints = s.waypoints.features.filter((f) => f.properties.id === 'cvn1').map((f) => f.properties.index);
    expect(cvnPoints).toEqual([1, 2, 3]);
    const hidden = buildStaticData(preset, { ...DEFAULT_VIEW, showRoutes: false }, null);
    expect(hidden.routes.features).toHaveLength(0);
    expect(hidden.waypoints.features).toHaveLength(0);
  });
});

describe('main group', () => {
  it('keeps the ships near the lead ship and leaves out far-off traffic', () => {
    const preset = PRESET_SCENARIOS[0];
    const states = statesAt(runScenario(preset), 0);
    const group = groupStates(states);
    expect(group).toHaveLength(4);
    expect(group).not.toContain(states[4]);
    expect(groupStates(states, 4)).toEqual([states[4]]);
    expect(groupStates([])).toEqual([]);
    expect(groupStates(states, 9)).toEqual([]);
  });
});
