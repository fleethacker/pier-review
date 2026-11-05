import { describe, expect, it } from 'vitest';
import { sampleStoryboard } from './fixtures';
import { hasMarker, locateStyle } from './styling';
import type { LocateMethod } from './types';

describe('locate styling', () => {
  it('draws exact and interpolated solid, others not at all', () => {
    expect(locateStyle('exact_fix')).toMatchObject({ marker: true, solid: true, opacity: 1 });
    expect(locateStyle('interpolated').marker).toBe(true);
    for (const m of ['gap', 'before_track', 'after_track', 'no_track', 'no_time'] as LocateMethod[]) {
      expect(locateStyle(m).marker).toBe(false);
      expect(locateStyle(m).warning).toMatch(/not established/);
    }
  });
  it('exact markers are larger than interpolated ones', () => {
    expect(locateStyle('exact_fix').sizePx).toBeGreaterThan(locateStyle('interpolated').sizePx);
  });
  it('only fixture events with a position get markers', () => {
    const marked = sampleStoryboard.events.filter(hasMarker).map((e) => e.located.method);
    expect(marked.sort()).toEqual(['exact_fix', 'exact_fix', 'interpolated']);
  });
});
