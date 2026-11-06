import { credentialState } from '../../lib/credentials';

export type StreamStatus = 'connecting' | 'open' | 'closed' | 'error';
export interface StreamCloseDetail { code: number; reason: string }

export interface StreamHandle {
  close(): void;
  /** Sends on the current socket. Returns false (and sends nothing) when the socket is not open. */
  send(data: string): boolean;
}

/**
 * JSON WebSocket that reconnects with a short backoff until closed. `limit`-style streams that end cleanly are
 * reported as 'closed' and not reopened.
 */
export function openJsonStream<T>(
  /** A function is re-evaluated on every reconnect, e.g. to resume after the last sequence received. */
  url: string | (() => string),
  onMessage: (message: T) => void,
  onStatus: (status: StreamStatus, close?: StreamCloseDetail) => void,
): StreamHandle {
  if (credentialState.get().configured) {
    onStatus('error');
    return { close() {}, send() { return false; } };
  }
  let socket: WebSocket | null = null;
  let closedByUs = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    onStatus('connecting');
    socket = new WebSocket(typeof url === 'function' ? url() : url);
    socket.onopen = () => {
      if (closedByUs) return;
      attempt = 0;
      onStatus('open');
    };
    socket.onmessage = (ev) => {
      if (closedByUs) return;
      try {
        onMessage(JSON.parse(String(ev.data)) as T);
      } catch {
        // A malformed frame should not kill the stream.
      }
    };
    socket.onerror = () => { if (!closedByUs) onStatus('error'); };
    socket.onclose = (ev) => {
      if (closedByUs) return;
      if ([1000, 1008, 4401, 4404].includes(ev.code)) {
        onStatus('closed', { code: ev.code, reason: ev.reason });
        return;
      }
      onStatus('error', { code: ev.code, reason: ev.reason });
      attempt += 1;
      timer = setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000));
    };
  };
  connect();

  return {
    send(data: string) {
      if (!socket || socket.readyState !== 1) return false;
      socket.send(data);
      return true;
    },
    close() {
      closedByUs = true;
      clearTimeout(timer);
      socket?.close();
    },
  };
}
