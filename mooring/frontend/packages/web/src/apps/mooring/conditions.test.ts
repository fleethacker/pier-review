import { describe, expect, it } from 'vitest';
import { compass, describeComponents, shipComponents, shipHeadingTrue } from './conditions';
import type { Berth } from './types';

// Berth face runs 105 true. Starboard side to: bow 105, pier on the starboard side (195 true).
const berth = { face_bearing_true_deg: 105 } as Berth;

describe('compass', () => {
  it('names bearings on the 16-point rose', () => {
    expect(compass(0)).toBe('N');
    expect(compass(200)).toBe('SSW');
    expect(compass(359)).toBe('N');
    expect(compass(-90)).toBe('W');
  });
});

describe('ship components', () => {
  it('heading follows the side to', () => {
    expect(shipHeadingTrue(berth, 'starboard')).toBe(105);
    expect(shipHeadingTrue(berth, 'port')).toBe(285);
  });

  it('wind from the pier side blows the ship off the pier', () => {
    const c = shipComponents(15, 20, berth, 'starboard'); // blowing toward 15 = from 195, the pier side
    expect(c.offPierKt).toBeCloseTo(20);
    expect(c.alongKt).toBeCloseTo(0);
    expect(describeComponents(c)).toEqual({ offPier: '20.0 kt off the pier', along: 'none' });
  });

  it('wind from the water side presses the ship onto the pier', () => {
    expect(shipComponents(195, 10, berth, 'starboard').offPierKt).toBeCloseTo(-10);
  });

  it('flow toward the bow is positive along the ship, for either side to', () => {
    expect(shipComponents(105, 3, berth, 'starboard').alongKt).toBeCloseTo(3);
    expect(describeComponents(shipComponents(285, 3, berth, 'starboard')).along).toBe('3.0 kt toward the stern');
    // Port side to turns the ship around but the pier stays on the 195 side, so off the pier is still toward 15.
    expect(shipComponents(15, 20, berth, 'port').offPierKt).toBeCloseTo(20);
    expect(shipComponents(285, 3, berth, 'port').alongKt).toBeCloseTo(3); // the bow now points 285
  });
});
