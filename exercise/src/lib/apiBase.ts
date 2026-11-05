const fallbackOrigin = typeof window === 'undefined' ? 'http://localhost:4100/' : window.location.href;

/**
 * Where the optional exercise service lives: the page's own origin by default (Vite forwards /api to it, see
 * vite.config.ts), or an absolute URL in VITE_EXERCISE_API_URL. The simulation runs in the browser; the service only
 * supplies the map token, the shared scenario library and the error log, and each of those falls back to this browser.
 */
export const EXERCISE_API_BASE = new URL(import.meta.env.VITE_EXERCISE_API_URL || '.', fallbackOrigin)
  .toString()
  .replace(/\/$/, '');
