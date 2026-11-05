import type { LibraryItem } from './serverApi';

/** Scenarios kept in this browser. The shared library lives on the server (serverApi.ts). */

const KEY = 'exercise.library.v1';

interface Stored {
  scenario: unknown;
  updatedAt: string;
}

export const slugify = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
    .replace(/-+$/g, '') || 'scenario';

function read(): Record<string, Stored> {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, Stored>) : {};
  } catch {
    return {};
  }
}

function write(all: Record<string, Stored>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    throw new Error('This browser would not let the scenario be saved (storage is full or blocked).');
  }
}

const describe = (id: string, s: Stored): LibraryItem => {
  const sc = (s.scenario ?? {}) as { name?: unknown; description?: unknown; units?: unknown };
  return {
    id,
    name: typeof sc.name === 'string' ? sc.name : id,
    description: typeof sc.description === 'string' ? sc.description : '',
    units: Array.isArray(sc.units) ? sc.units.length : 0,
    updatedAt: s.updatedAt,
  };
};

export function listLocal(): LibraryItem[] {
  return Object.entries(read())
    .map(([id, s]) => describe(id, s))
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function loadLocal(id: string): { scenario: unknown; updatedAt: string } | null {
  const s = read()[id];
  return s ? { scenario: s.scenario, updatedAt: s.updatedAt } : null;
}

export function saveLocal(id: string, scenario: unknown): { updatedAt: string; created: boolean } {
  const all = read();
  const created = !(id in all);
  const updatedAt = new Date().toISOString();
  all[id] = { scenario, updatedAt };
  write(all);
  return { updatedAt, created };
}

export function deleteLocal(id: string): void {
  const all = read();
  delete all[id];
  write(all);
}
