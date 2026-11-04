import { describe, expect, it } from 'vitest';
import { distanceM, stationFrom } from './geo';
import { PRESET_SCENARIOS, blankScenario } from './scenarios';
import { buildFrameData, buildStaticData, DEFAULT_VIEW, shipPoint } from './scene';
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
    expect(f.hulls.features).toHaveLength(preset.units.length);
    expect(f.halos.features).toHaveLength(preset.units.length);
    expect(f.markers.features).toHaveLength(preset.units.length);
    expect(f.parts.features.length).toBeGreaterThan(preset.units.length);
    for (const h of f.hulls.features) {
      const ring = h.geometry.coordinates[0];
      expect(ring[0]).toEqual(ring[ring.length - 1]);
    }
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
