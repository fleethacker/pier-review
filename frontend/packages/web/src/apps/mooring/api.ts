import createClient from 'openapi-fetch';
import type { paths as ModelingPaths } from '../../api/modeling';
import type { paths as AgentPaths } from '../../api/agents';
import type { JobAccepted, JobStatus } from './types';

const fallbackOrigin = typeof window === 'undefined' ? 'http://localhost:4000/' : window.location.href;

/** Same-origin proxy paths by default (see vite.config.ts); override with an absolute URL in .env. */
function resolveBase(configured: string | undefined, fallback: string): string {
  return new URL(configured || fallback, fallbackOrigin).toString().replace(/\/$/, '');
}

export const MODELING_BASE = resolveBase(import.meta.env.VITE_MODELING_URL, 'api/modeling');
export const AGENTS_BASE = resolveBase(import.meta.env.VITE_AGENTS_URL, 'api/agents');

export const modeling = createClient<ModelingPaths>({ baseUrl: MODELING_BASE });
export const agents = createClient<AgentPaths>({ baseUrl: AGENTS_BASE });

export function wsUrl(base: string, path: string, query: Record<string, string | number | undefined>): string {
  const url = new URL(`${base}${path}`);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  for (const [k, v] of Object.entries(query)) if (v !== undefined) url.searchParams.set(k, String(v));
  return url.toString();
}

/** Throws a readable error for non-2xx openapi-fetch results. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  const detail = result.error ? JSON.stringify(result.error).slice(0, 300) : result.response.statusText;
  throw new Error(`${result.response.status} ${result.response.url.replace(/^https?:\/\/[^/]+/, '')}: ${detail}`);
}

/** Polls a 202 job until it finishes. `base` is the service the job belongs to. */
export async function awaitJob<T>(
  base: string,
  accepted: JobAccepted,
  onProgress?: (progress: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  const origin = new URL(base).origin;
  const basePath = new URL(base).pathname.replace(/\/$/, '');
  // status_url is rooted at the service ("/api/v1/jobs/..."); our base may carry a proxy prefix.
  const url = `${origin}${basePath}${accepted.status_url}`;
  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const res = await fetch(url, { signal });
    if (!res.ok) throw new Error(`Job status ${res.status}`);
    const job = (await res.json()) as JobStatus & { result?: T; error?: string | null };
    onProgress?.(job.progress ?? 0);
    if (job.state === 'succeeded') return job.result as T;
    if (job.state === 'cancelled') throw new Error('Job cancelled');
    if (job.state === 'failed') {
      throw new Error(job.error ?? `Job failed`);
    }
    await new Promise((r) => setTimeout(r, 400));
  }
}
