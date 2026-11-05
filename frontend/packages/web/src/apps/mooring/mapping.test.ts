import { describe, expect, it } from 'vitest';
import { entityToFrame } from '../../scene/geometry';
import * as mapping from './mapping';
import { partsName, lineLinks, buildScene, envReadouts, envVectors, hullPoints, pierEntities, shipEntities, shipPose } from './mapping';
import { ft } from './units';
import type { Berth, ShipClass } from './types';

const berth = {
  berth_id: 'B',
  name: 'Test pier',
  face_bearing_true_deg: 105,
  origin_lat: 36.9,
  origin_lon: -76.3,
  face_length_ft: 1000,
  deck_height_mllw_ft: 11,
  depth_profile: [],
  structure: 'open_pile',
  env_station_ids: { wind: '', current: '', water_level: '' },
  provenance: { source: 'test', confidence: 'mock' },
  fittings: [
    { fitting_id: 'P1', kind: 'bollard_special_b', x_ft: 100, y_ft: -6, capacity_nominal_lbf: 1, capacity_horizontal_lbf: 2, condition: 'good' },
    { fitting_id: 'P2', kind: 'cleat_42', x_ft: 300, y_ft: -45, capacity_nominal_lbf: 1, capacity_horizontal_lbf: 2, condition: 'suspect' },
  ],
  fenders: [{ fender_id: 'F1', kind: 'camel', x_ft: 400, length_ft: 40, standoff_ft: 12, stiffness_lbf_per_ft: 1, rated_energy_ftlbf: 1 }],
} as unknown as Berth;

const ship = {
  class_id: 'TST',
  name: 'Test ship',
  hull_type: 'DDG',
  loa_ft: 500,
  lwl_ft: 460,
  beam_ft: 60,
  mst_class: 'II',
  loading_conditions: [{ name: 'full_load', displacement_lt: 9000, draft_fwd_ft: 30, draft_aft_ft: 30, freeboard_ft: 20 }],
  fittings: [
    { fitting_id: 'BITT-1S', kind: 'bitt', x_ft: 200, y_ft: -9, z_ft: 24, side: 'starboard', swl_lbf: 385000 },
    { fitting_id: 'BITT-1P', kind: 'bitt', x_ft: 200, y_ft: 9, z_ft: 24, side: 'port', swl_lbf: 385000 },
  ],
} as unknown as ShipClass;

describe('ship placement', () => {
  it('starboard side to: bow toward +x, ship offset from the face by beam/2 + standoff', () => {
    const pose = shipPose(ship, 'starboard', 650, 12);
    expect(pose.headingDeg).toBe(0);
    expect(pose.x).toBeCloseTo(ft(650));
    expect(pose.y).toBeCloseTo(ft(30 + 12));
    // The starboard bow bitt is ahead of midships in +x and closer to the pier (smaller y).
    const [x, y] = entityToFrame(pose, ft(200), ft(-9));
    expect(x).toBeCloseTo(ft(850));
    expect(y).toBeCloseTo(ft(42 - 9));
  });

  it('port side to: bow toward -x, port fittings face the pier', () => {
    const pose = shipPose(ship, 'port', 650, 12);
    expect(pose.headingDeg).toBe(180);
    const [x, y] = entityToFrame(pose, ft(200), ft(9));
    expect(x).toBeCloseTo(ft(450));
    expect(y).toBeCloseTo(ft(42 - 9));
  });

  it('only shows bitts on the side that faces the pier', () => {
    const s = shipEntities(ship, 'full_load', 'starboard', 650, 12, null, true, berth);
    expect(s.map((e) => e.id).filter((id) => !id.startsWith('ship-part') && !id.startsWith('ship-'))).toEqual(['ship', 'sfit:BITT-1S']);
    const p = shipEntities(ship, 'full_load', 'port', 650, 12, null, true, berth);
    expect(p.map((e) => e.id).filter((id) => !id.startsWith('ship-part') && !id.startsWith('ship-'))).toEqual(['ship', 'sfit:BITT-1P']);
  });

  it('is only draggable when the class has fittings to moor with', () => {
    const hullOf = (editable: boolean) =>
      shipEntities(ship, 'full_load', 'starboard', 650, 12, null, editable, berth).find((e) => e.id === 'ship')!;
    expect(hullOf(true).editable).toBeDefined();
    expect(hullOf(false).editable).toBeUndefined();
  });

  it('builds a hull that spans LOA and beam', () => {
    const pts = hullPoints(500, 60);
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(ft(500));
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(ft(60));
  });
});

describe('buildScene', () => {
  it('draws pier, fittings, fenders, ship, links and env arrows in the berth frame', () => {
    const scene = buildScene({
      berth,
      ship,
      loading: 'full_load',
      side: 'starboard',
      shipXFt: 650,
      standoffFt: 12,
      lines: [{ line_number: 1, spec_id: 'S', parts: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1' }],
      analysis: null,
      env: {
        source: 'mock', wind_speed_kt: 20, wind_gust_kt: 28, wind_from_true_deg: 200, current_speed_kt: 1,
        current_set_true_deg: 10, water_level_mllw_ft: 0, air_density_kgm3: 1.2, water_density_kgm3: 1020,
      } as never,
    });
    expect(scene.frame.xBearingTrueDeg).toBe(105);
    const ids = scene.entities.map((e) => e.id);
    expect(ids).toEqual(expect.arrayContaining(['pier', 'pier:P1', 'pier:P2', 'fender:F1', 'ship', 'sfit:BITT-1S']));
    expect(scene.links).toHaveLength(1);
    expect(scene.links[0].from.entityId).toBe('ship');
    expect(scene.vectors.map((v) => v.id)).toEqual(['wind', 'current']);
    // Suspect fittings are shown in amber, not the normal color.
    const p2 = scene.entities.find((e) => e.id === 'pier:P2')!;
    expect(p2.color).not.toBe(scene.entities.find((e) => e.id === 'pier:P1')!.color);
  });

  it('draws only the pier when no ship is chosen', () => {
    const scene = buildScene({
      berth, ship: null, loading: '', side: 'starboard', shipXFt: 0, standoffFt: 3, lines: [], analysis: null, env: null,
    });
    expect(scene.entities.some((e) => e.kind === 'ship')).toBe(false);
    expect(scene.vectors).toEqual([]);
  });
});

describe('environment arrows', () => {
  it('points wind toward where it blows to (from + 180) and current toward its set', () => {
    const frame = { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 90 };
    // x bearing 90: bearing 90 is local angle 0, bearing 0 (north) is local angle 90.
    const env = {
      wind_from_true_deg: 270, wind_speed_kt: 10, wind_gust_kt: 10, current_speed_kt: 1, current_set_true_deg: 0,
    } as never;
    const [wind, current] = envVectors(frame, env, { x: 0, y: 0 });
    expect(wind.angleDeg).toBeCloseTo(0); // from the west, blowing east
    expect(current.angleDeg).toBeCloseTo(90); // flowing north
  });
});

describe('tugScene', () => {
  const shipWithPush = {
    ...ship,
    push_points: [
      { push_point_id: 'PP-FWD-P', x_ft: 150, side: 'port', max_force_lbf: 1 },
      { push_point_id: 'PP-FWD-S', x_ft: 150, side: 'starboard', max_force_lbf: 1 },
    ],
  } as unknown as ShipClass;
  const frame = { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 105 };

  it('puts tugs on the water side of a starboard-side-to ship, pushing toward the pier', () => {
    const { tugScene } = mapping;
    const out = tugScene(
      shipWithPush, 'starboard', 650, 12,
      [{ tug_id: 'T1', push_point_id: 'PP-FWD-P', mode: 'push', force_lbf: 36000, direction_true_deg: 195 }],
      frame,
    );
    const tug = out.entities.find((e) => e.kind === 'tug')!;
    expect(out.entities.filter((e) => e.kind === 'wake')).toHaveLength(1);
    // Port side is the water side; the ship centerline is at y = 42 ft, so the tug sits further into the water.
    expect(tug.pose.y).toBeGreaterThan(ft(42 + 30));
    expect(tug.pose.x).toBeCloseTo(ft(650 + 150));
    // Bearing 195 is the direction of -y for a frame whose +x bearing is 105: local angle 270.
    expect(out.vectors[0].angleDeg).toBeCloseTo(270);
  });

  it('skips assignments whose push point is unknown or direction missing', () => {
    const { tugScene } = mapping;
    const out = tugScene(
      shipWithPush, 'starboard', 650, 12,
      [
        { tug_id: 'T1', push_point_id: 'NOPE', mode: 'push', force_lbf: 1, direction_true_deg: 195 },
        { tug_id: 'T2', push_point_id: 'PP-FWD-P', mode: 'standby', force_lbf: 0 },
      ],
      frame,
    );
    expect(out.entities.filter((e) => e.kind === 'tug').map((e) => e.label)).toEqual(['T2']);
    expect(out.vectors).toEqual([]);
  });
});

describe('superstructure', () => {
  const pose = { x: 0, y: 0, z: 0, headingDeg: 0 };

  it('differs by hull type and stands in for the ship when clicked', () => {
    const ddg = mapping.superstructure({ ...ship, hull_type: 'DDG' } as ShipClass, pose, 6);
    const cvn = mapping.superstructure({ ...ship, hull_type: 'CVN', loa_ft: 1092, beam_ft: 134 } as ShipClass, pose, 6);
    expect(ddg.length).toBe(3);
    expect(cvn.length).toBe(2);
    for (const part of [...ddg, ...cvn]) {
      expect(part.selectsId).toBe('ship');
      expect(part.pose.z).toBeGreaterThanOrEqual(6);
    }
  });

  it('keeps every block within the ship length', () => {
    for (const hull of ['DDG', 'CG', 'CVN', 'LHD', 'XYZ']) {
      const parts = mapping.superstructure({ ...ship, hull_type: hull } as ShipClass, pose, 6);
      for (const part of parts) {
        if (part.geometry.type !== 'polygon') continue;
        const xs = part.geometry.points.map((p) => p[0]);
        expect(Math.min(...xs)).toBeGreaterThanOrEqual(-ft(250.01));
        expect(Math.max(...xs)).toBeLessThanOrEqual(ft(250.01));
      }
    }
  });

  it('puts the carrier island on the starboard side of the ship frame', () => {
    const cvn = mapping.superstructure({ ...ship, hull_type: 'CVN' } as ShipClass, pose, 6);
    const island = cvn[1];
    if (island.geometry.type !== 'polygon') throw new Error('expected polygon');
    expect(island.geometry.points.every((p) => p[1] < 0)).toBe(true);
  });

  it('labels each arrow with the variable name and speed only, in its own color', () => {
    const frame = { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 90 };
    const env = {
      wind_from_true_deg: 270, wind_speed_kt: 22, wind_gust_kt: 30, current_speed_kt: 0.6, current_set_true_deg: 0,
    } as never;
    const [wind, current] = envVectors(frame, env, { x: 0, y: 0 });
    expect(wind.label).toBe('WIND 22 kt');
    expect(current.label).toBe('CURRENT 0.6 kt');
    expect(wind.color).not.toBe(current.color);
  });

  it('shows the water level as a readout with no arrow', () => {
    const [up] = envReadouts({ water_level_mllw_ft: 1.8 } as never, { x: 0, y: 0 });
    expect(up.label).toBe('WATER LEVEL +1.8 ft');
    expect(up.selectable).toBe(false);
    expect(envReadouts({ water_level_mllw_ft: -0.5 } as never, { x: 0, y: 0 })[0].label).toBe('WATER LEVEL -0.5 ft');
    expect(envReadouts(null, { x: 0, y: 0 })).toEqual([]);
  });
});

describe('visual effects data', () => {
  it('gives wind and current a flow, faster for stronger wind, with gust surge', () => {
    const frame = { lonDeg: 0, latDeg: 0, xBearingTrueDeg: 90 };
    const mk = (wind: number, gust: number) =>
      envVectors(frame, { wind_from_true_deg: 0, wind_speed_kt: wind, wind_gust_kt: gust, current_speed_kt: 1, current_set_true_deg: 0 } as never, { x: 0, y: 0 });
    const [calm, , ] = mk(5, 5);
    const [strong, current] = mk(30, 45);
    expect(strong.flow!.mps).toBeGreaterThan(calm.flow!.mps);
    expect(calm.flow!.gustiness).toBe(0);
    expect(strong.flow!.gustiness).toBeCloseTo(0.5);
    expect(current.flow!.mps).toBeGreaterThan(0);
  });

  it('puts a status-colored halo and a shadow under the ship that stand in for the ship when clicked', () => {
    const s = shipEntities(ship, 'full_load', 'starboard', 650, 12, { status: 'RED', result: { lines: [], ship_fittings: [] } } as never, true, berth);
    const halo = s.find((e) => e.id === 'ship-halo')!;
    const shadow = s.find((e) => e.id === 'ship-shadow')!;
    expect(halo.status).toBe('RED');
    expect(halo.selectsId).toBe('ship');
    expect(shadow.selectsId).toBe('ship');
    expect(halo.pose.z).toBeLessThan(shadow.pose.z);
    expect(s.findIndex((e) => e.id === 'ship-halo')).toBeLessThan(s.findIndex((e) => e.id === 'ship'));
  });

  it('lights the pier edge', () => {
    const edge = pierEntities(berth, null).find((e) => e.id === 'pier-edge')!;
    expect(edge.selectable).toBe(false);
    expect(edge.noOutline).toBe(true);
  });
});

describe('doubled-up lines', () => {
  it('names the part counts the way they are used aboard', () => {
    expect(partsName(1)).toBe('single');
    expect(partsName(2)).toBe('tanker moor ×2');
    expect(partsName(3)).toBe('doubled up ×3');
  });

  it('tags a doubled line on the canvas, draws it heavier, and leaves a single line plain', () => {
    const mk = (parts: 1 | 3) =>
      lineLinks(berth, ship, [{ line_number: 4, role: 'stern', spec_id: 'N', parts, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1' } as never], null)[0];
    const single = mk(1);
    const doubled = mk(3);
    expect(single.label).toBe('L4');
    expect(doubled.label).toBe('L4 ×3');
    expect(doubled.strands).toBe(3);
    expect(single.strands).toBe(1);
    expect(doubled.widthPx!).toBeGreaterThan(single.widthPx!);
  });
});


it.each(['invalid', 'unknown', undefined])('does not color lines/fittings from %s analysis as passing', (state) => {
  const analysis = { status: 'RED', validity: state ? { state } : undefined, result: {
    lines: [{ line_number: 1, status: 'GREEN', tension_lbf: 0, pct_wll: 0, pct_mbs: 0, length_ft: 1, horiz_angle_deg: 0, vert_angle_deg: 0 }],
    pier_fittings: [{ fitting_id: 'P1', status: 'GREEN', load_lbf: 0, pct: 0, lines: [1] }],
    ship_fittings: [{ fitting_id: 'BITT-1S', status: 'GREEN', load_lbf: 0, pct: 0, lines: [1] }],
  } } as never;
  const links = lineLinks(berth, ship, [{ line_number: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1', spec_id: 'S', parts: 1 }], analysis);
  expect(links[0].status).toBeUndefined();
  expect(links[0].label).not.toContain('%');
  expect(links[0].props?.some(p => p.label === 'Tension')).toBe(false);
  const pier = pierEntities(berth, analysis).find(e => e.id === mapping.IDS.pierFitting('P1'))!;
  const fitting = shipEntities(ship, 'full_load', 'starboard', 650, 12, analysis, true, berth).find(e => e.id === 'sfit:BITT-1S')!;
  for (const entity of [pier, fitting]) {
    expect(entity.status).toBeUndefined();
    expect(entity.props?.some(p => p.label === 'Load')).toBe(false);
  }
});


it.each(['valid', 'limited'])('retains evaluated line values for %s analysis', (state) => {
  const analysis = { validity: { state }, result: { lines: [
    { line_number: 1, status: 'GREEN', tension_lbf: 100, pct_wll: 12, pct_mbs: 4, length_ft: 30, horiz_angle_deg: 25, vert_angle_deg: 15 },
  ] } } as never;
  const [link] = lineLinks(berth, ship, [{ line_number: 1, ship_fitting_id: 'BITT-1S', pier_fitting_id: 'P1', spec_id: 'S', parts: 1 }], analysis);
  expect(link.status).toBe('GREEN');
  expect(link.label).toContain('12%');
  expect(link.props?.find(p => p.label === 'Tension')?.value).toBe('100 lbf');
});
