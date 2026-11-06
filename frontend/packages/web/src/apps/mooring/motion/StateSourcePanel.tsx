import { useState } from 'react';
import { Button, inputClass } from '../../../shell/ui';
import type { MotionController, MotionState } from './controller';
import type { StateInput } from './workspace';

export function StateSourcePanel({ c, s }: { c: MotionController; s: MotionState }) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const snapshot = s.frame?.stateInputs.at(-1) ?? (s.importedState?.run_id === s.frame?.runId ? s.importedState : null);
  const attached = !!snapshot;
  const shipSnapshot = [...(s.frame?.stateInputs ?? [])].reverse().find((entry) => entry.input.entity === 'ship') ?? (snapshot?.input.entity === 'ship' ? snapshot : null);
  const paused = s.lifecycle === 'paused' || s.lifecycle === 'created' || s.lifecycle === 'reset';
  const ship = s.frame?.ship;
  const canCopy = !!s.workspace && !!ship && ship.surgeFps != null && ship.swayFps != null && ship.yawDegps != null;
  return <div className="space-y-2 text-[10px]">
    <p className="text-mil-dim">Own ship: {s.source === 'recording' ? 'recorded simulation' : 'backend simulation'}. {shipSnapshot ? `Seeded from imported ${shipSnapshot.input.source} evidence.` : 'No telemetry input selected.'}</p>
    {s.workspace?.scenario.configuration.environment_mode === 'live' && <p className="text-mil-dim">Environment: acquired snapshot held for this run, not a continuous feed. Source {s.workspace.environment.source}; valid at {s.workspace.environment.valid_at_utc ?? 'unavailable'}. Observation age at acquisition {s.workspace.environment.metadata?.age_s == null ? 'unavailable' : `${s.workspace.environment.metadata.age_s.toFixed(0)} s`}.</p>}
    {attached && <div className="border border-mil-border p-2 text-mil-text"><p>{snapshot.input.entity} {snapshot.input.entity_id} · {snapshot.input.source_name ?? snapshot.input.source} · quality {snapshot.input.quality ?? 'unknown'}</p><p className="text-mil-dim">Observed {snapshot.input.observed_at_utc}<br />Age at acceptance {snapshot.age_s.toFixed(1)} s<br />Evidence {snapshot.input_hash.slice(0, 16)}</p><p className="mt-1 text-mil-amber">{snapshot.qualification} · imported sample, not a connected hardware feed</p></div>}
    {s.frame && s.frame.forcingTimeOffsetS > 0 && <p className="text-mil-dim">Environmental source phase: {(s.frame.tS + s.frame.forcingTimeOffsetS).toFixed(1)} s; run clock restarted at imported state.</p>}
    {s.workspace && <details><summary className="cursor-pointer text-mil-cyan">Import supplied ship or tug state</summary><form className="mt-2 space-y-2" onSubmit={(e) => {
      e.preventDefault();
      try {
        const input: unknown = JSON.parse(text);
        if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Supply one JSON state observation.');
        setError(null); void c.importState(input as StateInput);
      } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    }}>
      <p className="text-mil-dim">Imports require a complete timestamped observation in the declared berth frame. The service checks identity, sequence, age and quality. A sensor label identifies supplied evidence; it does not connect hardware.</p>
      <Button type="button" size="sm" variant="secondary" disabled={!canCopy} onClick={() => {
        if (!s.workspace || !ship || ship.surgeFps == null || ship.swayFps == null || ship.yawDegps == null) return;
        const sample: StateInput = { entity: 'ship', entity_id: s.workspace.ship.class_id, frame: 'berth', berth_id: s.workspace.berth.berth_id, source: 'synthetic', source_name: 'Copied backend simulation frame for explicit editing', observed_at_utc: new Date().toISOString(), sequence: (s.importedState?.input.sequence ?? 0) + 1, x_ft: ship.x_ft, y_ft: ship.y_ft, heading_true_deg: ship.headingTrueDeg, surge_fps: ship.surgeFps, sway_fps: ship.swayFps, yaw_degps: ship.yawDegps, measured_acceleration: null, quality: 'unknown' };
        setText(JSON.stringify(sample, null, 2)); setError(null);
      }}>Copy current simulated sample</Button>
      <label className="block text-mil-dim">State observation JSON<textarea className={`${inputClass} mt-1 h-40 resize-y font-mono text-[10px]`} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} placeholder={'{"entity":"ship","entity_id":"…","frame":"berth","berth_id":"…","source":"sensor","observed_at_utc":"…","sequence":1,"x_ft":…,"y_ft":…,"heading_true_deg":…,"surge_fps":…,"sway_fps":…,"yaw_degps":…}'} /></label>
      <p className="text-[9px] text-mil-dim">x: along pier; y: off pier (ft). Body surge: forward; sway: port (ft/s). Yaw: counterclockwise (°/s). Optional measured acceleration remains evidence, not inferred force.</p>
      <Button size="sm" type="submit" disabled={!paused || s.link !== 'open' || s.stateImportBusy || !text.trim()}>{s.stateImportBusy ? 'Checking input…' : 'Import into paused run'}</Button>
      {!paused && <p className="text-mil-amber">Pause before importing a state. Start then continues backend simulation from the accepted observation.</p>}
      {(error || s.stateImportError) && <p role="alert" className="text-mil-red">{error ?? s.stateImportError}</p>}
    </form></details>}
  </div>;
}
