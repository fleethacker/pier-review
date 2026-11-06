import createClient from 'openapi-fetch';
import { runtimeAuthHeaders } from '../../lib/credentials';
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

/** Runtime credential, entered by the current user; never a build-time environment variable. */
export const authHeaders = runtimeAuthHeaders;

export const modeling = createClient<ModelingPaths>({ baseUrl: MODELING_BASE });
export const agents = createClient<AgentPaths>({ baseUrl: AGENTS_BASE });
for (const client of [modeling, agents]) client.use({ onRequest({ request }) {
  for (const [name, value] of Object.entries(authHeaders())) request.headers.set(name, value);
  return request;
} });

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
    const res = await fetch(url, { signal, headers: authHeaders() });
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

/**
 * Readable text for a failed call. `unwrap` throws "<status> <path>: <body>"; users should see what went wrong and
 * what to do, not the raw JSON. Unknown failures keep their own message, shortened.
 */
export function describeError(e: unknown): string {
  const text = e instanceof Error ? e.message : String(e);
  if (e instanceof DOMException && e.name === 'AbortError') return 'Cancelled.';
  if (/Failed to fetch|NetworkError|Load failed/i.test(text)) return 'Could not reach the service. Check that it is running, then try again.';
  const status = /^(\d{3}) /.exec(text)?.[1];
  const tool = /Tool '([^']+)' exceeded its (\d+(?:\.\d+)?) s timeout/.exec(text.replace(/\\"/g, '"').replace(/\\'/g, "'"));
  if (tool) return `A calculation took too long (${tool[1]} passed its ${Number(tool[2])} s limit). The machine may be busy: try again in a moment.`;
  switch (status) {
    case '429':
      return 'The service is busy (too many requests or sessions). Wait a few seconds and try again.';
    case '502':
      return 'The service could not be reached through the proxy. Check that it is running, then try again.';
    case '503':
      return 'The service is not available right now. Nothing was changed; try again shortly.';
    case '504':
      return 'The service took too long to answer. The machine may be busy: try again in a moment.';
    case '404':
      return 'That item was not found. It may have been removed or never saved.';
    case '422': {
      const detail = /"msg"\s*:\s*"([^"]+)"/.exec(text)?.[1] ?? /"detail"\s*:\s*"([^"]+)"/.exec(text)?.[1];
      return detail ? `The service rejected the request: ${detail}` : 'The service rejected the request as invalid.';
    }
    default:
      return text.length > 240 ? `${text.slice(0, 237)}…` : text;
  }
}
