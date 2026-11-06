import { afterEach, expect, it, vi } from 'vitest';
import { openJsonStream } from '../streams';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('forwards terminal close evidence without reconnecting a rejected command', () => {
  vi.useFakeTimers();
  const sockets: FakeSocket[] = [];
  class FakeSocket {
    onclose: ((e: { code: number; reason: string }) => void) | null = null;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((e: { data: string }) => void) | null = null;
    readyState = 1;
    constructor() { sockets.push(this); }
    send() {}
    close() {}
  }
  vi.stubGlobal('WebSocket', FakeSocket);
  const status = vi.fn();
  const handle = openJsonStream('ws://test/sim', () => undefined, status);
  sockets[0].onopen?.();
  sockets[0].onclose?.({ code: 1008, reason: 'Tug direction rejected' });
  expect(status).toHaveBeenLastCalledWith('closed', { code: 1008, reason: 'Tug direction rejected' });
  vi.advanceTimersByTime(60000);
  expect(sockets).toHaveLength(1);
  handle.close();
});
