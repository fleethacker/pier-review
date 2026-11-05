import type { LocateMethod, StoryboardEvent } from './types';

export interface LocateStyle {
  /** Draw a marker on the map at the located position. */
  marker: boolean;
  /** Solid fill (position established from fixes) vs. not drawn. */
  solid: boolean;
  opacity: number;
  sizePx: number;
  label: string;
  /** Shown in the event list when no marker can be drawn. */
  warning: string | null;
}

const STYLES: Record<LocateMethod, LocateStyle> = {
  exact_fix: { marker: true, solid: true, opacity: 1, sizePx: 12, label: 'exact fix', warning: null },
  interpolated: { marker: true, solid: true, opacity: 0.85, sizePx: 10, label: 'interpolated', warning: null },
  gap: { marker: false, solid: false, opacity: 0, sizePx: 0, label: 'in recording gap', warning: 'Position not established: the bracketing fixes are further apart than the interpolation limit.' },
  before_track: { marker: false, solid: false, opacity: 0, sizePx: 0, label: 'before track', warning: 'Position not established: the event is before the first recorded fix.' },
  after_track: { marker: false, solid: false, opacity: 0, sizePx: 0, label: 'after track', warning: 'Position not established: the event is after the last recorded fix.' },
  no_track: { marker: false, solid: false, opacity: 0, sizePx: 0, label: 'no track', warning: 'Position not established: the mission has no recorded track.' },
  no_time: { marker: false, solid: false, opacity: 0, sizePx: 0, label: 'no time', warning: 'Position not established: the event has no usable time.' },
};

export function locateStyle(method: LocateMethod): LocateStyle {
  return STYLES[method];
}

/** A marker is drawn only when the method gives a style with a marker AND the server returned a position. */
export function hasMarker(e: StoryboardEvent): boolean {
  return STYLES[e.located.method].marker && e.located.lat != null && e.located.lon != null;
}

export const KIND_COLOR: Record<StoryboardEvent['kind'], string> = { image: '#00e5ff', report: '#ffc107' };
export const KIND_ICON: Record<StoryboardEvent['kind'], string> = { image: '▣', report: '☰' };

/** Discrepancy above this is flagged amber on the map and list. */
export const DISCREPANCY_WARN_M = 100;
