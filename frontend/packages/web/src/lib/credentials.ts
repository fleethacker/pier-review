import { Store } from './store';

// Memory only, scoped to this browser tab. Never bundled, persisted, logged or put in a URL.
let bearer = '';
export const credentialState = new Store({ configured: false, revision: 0 });
export const GATEWAY_REQUIRED = 'Live WebSocket features require the authenticated gateway. Direct API credentials support HTTP and Planner events only.';
export function setRuntimeCredential(value: string): void {
  bearer = value.trim();
  credentialState.set((state) => ({ configured: !!bearer, revision: state.revision + 1 }));
}
export function runtimeAuthHeaders(): Record<string, string> {
  return bearer ? { Authorization: `Bearer ${bearer}` } : {};
}
