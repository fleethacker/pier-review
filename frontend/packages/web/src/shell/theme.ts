import type { Status } from '../scene/types';

export const STATUS_COLOR: Record<Status, string> = {
  GREEN: '#00e676',
  AMBER: '#ffc107',
  RED: '#ff1744',
  NONE: '#8ba4c4',
};

export const COLORS = {
  water: '#123a5c',
  background: '#0a1628',
  selection: '#00e5ff',
  text: '#d6e4f5',
  dim: '#7390b0',
};

export function colorFor(status: Status | undefined, fallback?: string): string {
  if (status && status !== 'NONE') return STATUS_COLOR[status];
  return fallback ?? STATUS_COLOR.NONE;
}
