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
