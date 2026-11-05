export function fmtUtc(v: string | number | null | undefined): string {
  if (v == null) return 'no time';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return 'no time';
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace(/Z$/, ' UTC');
}

export function fmtClock(v: number): string {
  return `${fmtUtc(v).slice(11, 19)} UTC`;
}

export function fmtDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  return h ? `${h} h ${m} min` : m ? `${m} min ${sec} s` : `${sec} s`;
}

export function fmtSimTime(s: number): string {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

export const num = (v: number | null | undefined, d = 1): string => (v == null || !Number.isFinite(v) ? '–' : v.toFixed(d));
