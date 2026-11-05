/// <reference lib="webworker" />
import { simulateChunk } from './montecarlo';
import type { RedTeamSpec, ScenarioConfig } from './types';

// Runs chunks of a red-team batch off the main thread. The scenario and settings arrive once; chunks are ranges of run numbers.
let base: ScenarioConfig | null = null;
let spec: RedTeamSpec | null = null;

self.onmessage = (e: MessageEvent<{ type: 'init'; base: ScenarioConfig; spec: RedTeamSpec } | { type: 'chunk'; k0: number; k1: number }>) => {
  const m = e.data;
  if (m.type === 'init') {
    base = m.base;
    spec = m.spec;
    return;
  }
  try {
    if (!base || !spec) throw new Error('The worker was not given a scenario.');
    (self as unknown as Worker).postMessage({ records: simulateChunk(base, spec, m.k0, m.k1) });
  } catch (err) {
    (self as unknown as Worker).postMessage({ error: err instanceof Error ? err.message : String(err) });
  }
};
