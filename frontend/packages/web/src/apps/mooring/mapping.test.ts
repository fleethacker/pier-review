import { describe, expect, it } from 'vitest';
import { entityToFrame } from '../../scene/geometry';
import * as mapping from './mapping';
import { buildScene, envVectors, hullPoints, shipEntities, shipPose } from './mapping';
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
    expect(s.map((e) => e.id)).toEqual(['ship', 'sfit:BITT-1S']);
    const p = shipEntities(ship, 'full_load', 'port', 650, 12, null, true, berth);
    expect(p.map((e) => e.id)).toEqual(['ship', 'sfit:BITT-1P']);
  });

  it('is only draggable when the class has fittings to moor with', () => {
    expect(shipEntities(ship, 'full_load', 'starboard', 650, 12, null, true, berth)[0].editable).toBeDefined();
    expect(shipEntities(ship, 'full_load', 'starboard', 650, 12, null, false, berth)[0].editable).toBeUndefined();
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
    expect(out.entities).toHaveLength(1);
    const tug = out.entities[0];
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
    expect(out.entities.map((e) => e.label)).toEqual(['T2']);
    expect(out.vectors).toEqual([]);
  });
});
