import { credentialState, runtimeAuthHeaders } from '../../lib/credentials';

type EventStream = Pick<EventSource, 'addEventListener' | 'close' | 'readyState' | 'onerror'>;

/** Native gateway events, or authenticated fetch streaming for runtime bearer access. Never puts keys in URLs. */
export function openAgentEvents(url: string): EventStream {
  if (!credentialState.get().configured) return new EventSource(url);
  const target = new EventTarget();
  const abort = new AbortController();
  const stream = {
    readyState: 0,
    onerror: null as EventSource['onerror'],
    addEventListener: target.addEventListener.bind(target) as EventSource['addEventListener'],
    close() { stream.readyState = 2; abort.abort(); },
  };
  void (async () => {
    try {
      const response = await fetch(url, { headers: { ...runtimeAuthHeaders(), Accept: 'text/event-stream' }, signal: abort.signal });
      if (!response.ok || !response.body) throw new Error(`Planner stream HTTP ${response.status}`);
      stream.readyState = 1;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (abort.signal.aborted) return;
        buffer += decoder.decode(value, { stream: !done });
        buffer = buffer.replace(/\r\n/g, '\n');
        let end: number;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const lines = buffer.slice(0, end).split('\n'); buffer = buffer.slice(end + 2);
          const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message';
          const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).replace(/^ /, '')).join('\n');
          if (data) target.dispatchEvent(new MessageEvent(event, { data }));
          if (abort.signal.aborted) return;
        }
        if (buffer.length > 262144) throw new Error('Planner event exceeded the supported message size');
        if (done) throw new Error('Planner stream closed before completion');
      }
    } catch {
      if (abort.signal.aborted) return;
      stream.readyState = 2;
      stream.onerror?.call(stream as unknown as EventSource, new Event('error'));
    }
  })();
  return stream;
}
