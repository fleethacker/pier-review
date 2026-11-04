export const FT_TO_M = 0.3048;
export const ft = (feet: number): number => feet * FT_TO_M;
export const toFt = (meters: number): number => meters / FT_TO_M;

export const fmt = {
  ft: (v: number, digits = 0) => `${v.toFixed(digits)} ft`,
  lbf: (v: number) => `${Math.round(v).toLocaleString('en-US')} lbf`,
  kt: (v: number, digits = 0) => `${v.toFixed(digits)} kt`,
  deg: (v: number) => `${Math.round(v)}°`,
  pct: (v: number) => `${v.toFixed(0)}%`,
};
