import { EXERCISE_API_BASE } from './lib/apiBase';

/** What the app asks of its optional service: a shared scenario library, the public map token and an error log. */

export interface LibraryItem {
  id: string;
  name: string;
  description: string;
  units: number;
  updatedAt: string;
}

export class ServerError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const base = () => `${EXERCISE_API_BASE}/api/v1/exercise`;
const TIMEOUT_MS = 8000;

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${base()}${path}`, { ...init, signal: ctl.signal, headers: { 'Content-Type': 'application/json', ...init.headers } });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // Not JSON: the status text will do.
      }
      throw new ServerError(res.status, detail || `Error ${res.status}`);
    }
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  } catch (e) {
    if (e instanceof ServerError) throw e;
    throw new ServerError(0, ctl.signal.aborted ? 'The server took too long to answer.' : 'Could not reach the server.');
  } finally {
    clearTimeout(timer);
  }
}

export const fetchConfig = () => call<{ mapboxToken: string | null }>('/config');
export const listShared = () => call<LibraryItem[]>('/scenarios');
export const loadShared = (id: string) => call<{ scenario: unknown; updatedAt: string }>(`/scenarios/${encodeURIComponent(id)}`);
export const saveShared = (id: string, scenario: unknown, baseUpdatedAt?: string) =>
  call<{ id: string; updatedAt: string; created: boolean }>(`/scenarios/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({ scenario, ...(baseUpdatedAt ? { baseUpdatedAt } : {}) }),
  });
export const deleteShared = (id: string) => call<void>(`/scenarios/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const postClientError = (report: { kind: string; message: string; stack?: string; page?: string; userAgent?: string }) =>
  call<void>('/client-errors', { method: 'POST', body: JSON.stringify(report), keepalive: true } as RequestInit);
