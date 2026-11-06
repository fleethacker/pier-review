import { afterEach, expect, it, vi } from 'vitest';
import { awaitJob } from './api';
import type { JobAccepted } from './types';

afterEach(() => vi.unstubAllGlobals());
it('stops polling a cancelled job', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ state: 'cancelled', progress: 0 }) });
  vi.stubGlobal('fetch', fetch);
  await expect(awaitJob('http://localhost/api/modeling', { status_url: '/api/v1/jobs/j' } as JobAccepted)).rejects.toThrow('Job cancelled');
  expect(fetch).toHaveBeenCalledTimes(1);
});


it('generated API clients read the current runtime key on every request (F12)', async () => {
  vi.resetModules();
  const seen: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    seen.push(request.headers.get('Authorization') ?? '');
    return new Response('[]', { headers: { 'Content-Type': 'application/json' } });
  }));
  const { modeling } = await import('./api');
  const { setRuntimeCredential } = await import('../../lib/credentials');
  setRuntimeCredential('first'); await modeling.GET('/api/v1/ships');
  setRuntimeCredential('second'); await modeling.GET('/api/v1/ships');
  setRuntimeCredential(''); await modeling.GET('/api/v1/ships');
  expect(seen).toEqual(['Bearer first', 'Bearer second', '']);
});
