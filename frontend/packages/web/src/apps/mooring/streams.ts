export type StreamStatus = 'connecting' | 'open' | 'closed' | 'error';

export interface StreamHandle {
  close(): void;
}

/**
 * JSON WebSocket that reconnects with a short backoff until closed. `limit`-style streams that end cleanly are
 * reported as 'closed' and not reopened.
 */
export function openJsonStream<T>(
  url: string,
  onMessage: (message: T) => void,
  onStatus: (status: StreamStatus) => void,
): StreamHandle {
  let socket: WebSocket | null = null;
  let closedByUs = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    onStatus('connecting');
    socket = new WebSocket(url);
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
        onStatus('closed');
        return;
      }
      onStatus('error');
      attempt += 1;
      timer = setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000));
    };
  };
  connect();

  return {
    close() {
      closedByUs = true;
      clearTimeout(timer);
      socket?.close();
    },
  };
}
