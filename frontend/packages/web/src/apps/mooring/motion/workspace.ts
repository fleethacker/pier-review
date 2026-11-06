import type { components } from '../../../api/modeling';
import { authHeaders, MODELING_BASE } from '../api';

type S = components['schemas'];
export type HelmOrder = S['HelmOrder'];
export type ControlsConfig = S['MotionControlsConfig'];
export type ControlState = S['MotionControlState'];
export type LoadingState = S['MotionLoadingState'];
export type LineControlState = S['MotionLineControlState'];
export type PayloadItem = S['PayloadItem'];
export type Prediction = S['MotionPredictionResponse'];
export type WorkspaceSpec = S['MotionWorkspaceSpec'];
export type WorkspaceCatalog = S['MotionWorkspaceCatalog'];
export type WorkspaceScenario = S['MotionWorkspaceScenario'];
export type WorkspaceSession = S['MotionWorkspaceSessionCreated'];

/** Small typed adapter for the Motion service, including proxy prefixes and runtime auth. */
export async function motionRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${MODELING_BASE}/api/v1/motion${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { ...authHeaders(), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal,
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(`Motion service ${res.status}: ${message.slice(0, 280)}`);
  }
  return await res.json() as T;
}

/** Close the WebSocket first; the server may need a short interval to finish its disconnect cleanup. */
export async function releaseMotionSession(id: string): Promise<void> {
  const waits = [100, 250, 500];
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(`${MODELING_BASE}/api/v1/motion/sessions/${encodeURIComponent(id)}`, { method: 'DELETE', headers: authHeaders() });
    if (res.ok || res.status === 404) return;
    if (res.status !== 409 || attempt >= waits.length) throw new Error(`Previous session could not be released (${res.status}). Its recording is retained by the service.`);
    await new Promise((resolve) => setTimeout(resolve, waits[attempt]));
  }
}
