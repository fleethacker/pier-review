import { postClientError } from './serverApi';

/** Tell the server about problems that happen in the browser, so they can be found in its log. Never includes a map token. */

const seen = new Set<string>();
const MAX_REPORTS = 20;

/** Anything shaped like a Mapbox token is blanked before it leaves the page. */
export const scrub = (text: string): string => text.replace(/\b[ps]k\.[\w-]+\.[\w-]+/g, '[token]');

export function reportClientError(kind: string, message: string, stack?: string): void {
  const text = scrub(message).slice(0, 1000);
  const key = `${kind}|${text}`;
  if (seen.has(key) || seen.size >= MAX_REPORTS) return;
  seen.add(key);
  postClientError({
    kind,
    message: text,
    ...(stack ? { stack: scrub(stack).slice(0, 4000) } : {}),
    page: typeof location === 'undefined' ? undefined : location.pathname.slice(0, 300),
    userAgent: typeof navigator === 'undefined' ? undefined : navigator.userAgent.slice(0, 300),
  }).catch(() => undefined); // Reporting is best effort: a failure here must never become another error.
}

/** Report uncaught errors and unhandled promise rejections while the exercise tab is open. Returns the way to stop. */
export function installErrorReporting(): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const onError = (e: ErrorEvent) => reportClientError('script', e.message || 'Script error', e.error instanceof Error ? e.error.stack : undefined);
  const onRejection = (e: PromiseRejectionEvent) => {
    const r = e.reason as unknown;
    reportClientError('promise', r instanceof Error ? r.message : String(r), r instanceof Error ? r.stack : undefined);
  };
  window.addEventListener('error', onError);
  window.addEventListener('unhandledrejection', onRejection);
  return () => {
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onRejection);
  };
}

/** For tests. */
export function resetReported(): void {
  seen.clear();
}
