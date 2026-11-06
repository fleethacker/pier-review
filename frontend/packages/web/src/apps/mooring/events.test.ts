import { afterEach, expect, it, vi } from 'vitest';
import { openAgentEvents } from './events';
import { setRuntimeCredential } from '../../lib/credentials';

afterEach(() => { setRuntimeCredential(''); vi.unstubAllGlobals(); });
it('streams bearer-authenticated SSE without a token in the URL and decodes split multiline events', async () => {
  setRuntimeCredential('per-user-key');
  const bytes = new TextEncoder();
  const chunks = ['event: step\r', '\ndata: {"iteration":1,\r\n', 'data: "summary":"sample"}\r\n\r\nevent: done\ndata: {}\n\n'];
  const fetch = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) {
    chunks.forEach((chunk) => controller.enqueue(bytes.encode(chunk))); controller.close();
  } })));
  vi.stubGlobal('fetch', fetch);
  const stream = openAgentEvents('https://example.invalid/events');
  const received: unknown[] = [];
  stream.addEventListener('step', (event) => received.push(JSON.parse((event as MessageEvent).data)));
  await new Promise<void>((resolve) => stream.addEventListener('done', () => { stream.close(); resolve(); }));
  expect(received).toEqual([{ iteration: 1, summary: 'sample' }]);
  expect(fetch).toHaveBeenCalledWith('https://example.invalid/events', expect.objectContaining({ headers: { Authorization: 'Bearer per-user-key', Accept: 'text/event-stream' } }));
  expect(fetch.mock.calls[0][0]).not.toContain('key');
});
it('reports an unauthorized or prematurely closed authenticated stream instead of hanging', async () => {
  setRuntimeCredential('wrong-key');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
  const stream = openAgentEvents('https://example.invalid/events');
  await new Promise<void>((resolve) => { stream.onerror = () => resolve(); });
  expect(stream.readyState).toBe(2);
});
