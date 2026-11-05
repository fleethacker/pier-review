import { useSyncExternalStore } from 'react';

export const FT_TO_M = 0.3048;
export const ft = (feet: number): number => feet * FT_TO_M;
export const toFt = (meters: number): number => meters / FT_TO_M;

const LBF_TO_KN = 0.00444822;
const HP_TO_KW = 0.7457;
const LT_TO_T = 1.01605;

export type UnitSystem = 'navy' | 'metric';

const STORAGE_KEY = 'mooring-units';
let system: UnitSystem = 'navy';
try {
  if (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'metric') system = 'metric';
} catch {
  // Storage can be blocked; Navy units are the default.
}
const listeners = new Set<() => void>();

export function getUnitSystem(): UnitSystem {
  return system;
}

export function setUnitSystem(next: UnitSystem): void {
  if (next === system) return;
  system = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Not persisted; still applies for this session.
  }
  listeners.forEach((l) => l());
}

export function subscribeUnits(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-renders the calling component when the unit system changes. */
export function useUnitSystem(): UnitSystem {
  return useSyncExternalStore(subscribeUnits, getUnitSystem);
}

const grouped = (v: number) => Math.round(v).toLocaleString('en-US');

/**
 * Display formatting. Values arrive in the contract's Navy units (ft, lbf, hp, long tons); metric converts here and
 * nowhere else. Speeds stay in knots in both systems, as is usual at sea.
 */
export const fmt = {
  ft: (v: number, digits = 0) =>
    system === 'metric' ? `${(v * FT_TO_M).toFixed(digits)} m` : `${v.toFixed(digits)} ft`,
  lbf: (v: number) => (system === 'metric' ? `${(v * LBF_TO_KN).toFixed(1)} kN` : `${grouped(v)} lbf`),
  lbfPerFt: (v: number) => (system === 'metric' ? `${(v * LBF_TO_KN * (1 / FT_TO_M)).toFixed(1)} kN/m` : `${grouped(v)} lbf/ft`),
  hp: (v: number) => (system === 'metric' ? `${grouped(v * HP_TO_KW)} kW` : `${grouped(v)} hp`),
  longTons: (v: number) => (system === 'metric' ? `${grouped(v * LT_TO_T)} t` : `${grouped(v)} LT`),
  kt: (v: number, digits = 0) => `${v.toFixed(digits)} kt`,
  deg: (v: number) => `${Math.round(v)}°`,
  pct: (v: number) => `${v.toFixed(0)}%`,
};

/** Length fields the user types into: the unit label, and conversions between display and contract (feet) values. */
export const lengthUnit = (): string => (system === 'metric' ? 'm' : 'ft');
export const lengthToDisplay = (feet: number): number => (system === 'metric' ? feet * FT_TO_M : feet);
export const lengthFromDisplay = (value: number): number => (system === 'metric' ? value / FT_TO_M : value);
