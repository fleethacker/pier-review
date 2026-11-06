import { useEffect, useRef, useState } from 'react';
import { cn } from '../../../lib/cn';
import { STATUS_COLOR } from '../../../shell/theme';
import { Button, inputClass } from '../../../shell/ui';
import { fmt, useUnitSystem } from '../units';
import { DEFAULT_FACE_BEARING } from './frames';
import type { Badge, ValidityState, ViewFrame } from './frames';
import type { MotionController, MotionState } from './controller';
import { clockText } from './clock';
import { LIVE_SPEEDS, REPLAY_SPEEDS } from './controller';
import { EnvironmentGlyph, MotionCanvas } from './MotionCanvas';
import { drawableWaterLevelFt } from './sceneMapper';
import { ScenarioSelector } from './ScenarioBuilder';
import { ManeuverControls } from './ManeuverControls';
import { SectionViews } from './SectionViews';
import type { SectionView } from './SectionViews';
import type { BasemapKind } from './basemap';
import type { FlowDisplay } from './EnvironmentFlow';
import { StateSourcePanel } from './StateSourcePanel';

const VALIDITY_COLOR: Record<ValidityState, string> = {
  valid: STATUS_COLOR.GREEN,
  limited: STATUS_COLOR.AMBER,
  invalid: STATUS_COLOR.RED,
  unknown: STATUS_COLOR.NONE,
};

const PROVENANCE_TEXT: Record<string, string> = {
  mock: 'MOCK: authored values, not physics',
  estimated: 'ESTIMATED: unqualified model',
  qualified: 'QUALIFIED',
  unknown: 'PROVENANCE UNKNOWN',
  legacy: 'LEGACY FRAME: no provenance supplied',
};

function Pill({ color, children, title }: { color: string; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider" style={{ color, borderColor: `${color}66`, background: `${color}14` }}>
      <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {children}
    </span>
  );
}

/** The mandatory badges: validity, provenance, frame schema, environment source and age. Always visible. */
export function Badges({ frame, state }: { frame: ViewFrame | null; state: MotionState }) {
  const badge: Badge | null = frame?.badge ?? null;
  const env = frame?.environment;
  const validity = badge?.validity ?? 'unknown';
  const provenance = badge?.provenance ?? 'unknown';
  const sourceText = env?.wind.source ?? env?.current.source ?? null;
  const ageS = env?.wind.ageS ?? env?.current.ageS ?? null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Frame validity and provenance">
      <Pill color={VALIDITY_COLOR[validity]} title={badge?.reasons.join('\n') || 'No validity reasons supplied'}>
        validity: {frame ? validity : 'no frame'}
      </Pill>
      <Pill color={provenance === 'qualified' ? STATUS_COLOR.GREEN : provenance === 'legacy' || provenance === 'unknown' ? STATUS_COLOR.NONE : STATUS_COLOR.AMBER} title={badge?.provenanceSource ?? undefined}>
        {PROVENANCE_TEXT[provenance] ?? provenance}
      </Pill>
      <Pill color="#8ba4c4">{frame ? (frame.rm0 ? 'rm0-v1' : 'legacy schema') : 'schema n/a'}</Pill>
      <Pill color={env ? '#8ba4c4' : STATUS_COLOR.NONE}>
        environment: {state.workspace?.scenario.configuration.environment_mode === 'live' ? 'held snapshot · ' : ''}{env ? `${sourceText ?? 'source not stated'}${ageS != null ? `, ${ageS.toFixed(0)} s old` : ', age not stated'}` : 'not in frame'}
      </Pill>
      {((state.forcingSynthetic ?? state.clock?.training) || state.workspace?.scenario.configuration.environment_mode === 'synthetic') && (
        <Pill color={STATUS_COLOR.AMBER} title="The forcing in this session is synthetic training data, not an observation or forecast.">
          training · synthetic forcing
        </Pill>
      )}
      <Pill color={state.source === 'live' ? '#00e5ff' : '#a78bfa'}>{state.source === 'live' ? 'simulation · backend stream' : state.source === 'recording' ? 'replay' : 'idle'}</Pill>
      {(frame?.stateInputs.length || (state.importedState && state.importedState.run_id === frame?.runId)) ? <Pill color={STATUS_COLOR.AMBER}>seed: imported {(frame?.stateInputs.at(-1) ?? state.importedState)?.input.source} state</Pill> : null}
      {state.forcingRevision && <Pill color="#8ba4c4">forcing revision: {state.forcingRevision}</Pill>}
      {frame?.assumedFaceBearing && <Pill color={STATUS_COLOR.AMBER} title="This frame carries no scene, so the berth orientation was assumed.">berth orientation assumed</Pill>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-mil-border px-3 py-2">
      <h3 className="mil-label mb-1 text-[10px]">{title}</h3>
      {children}
    </section>
  );
}

const NA = <span className="text-mil-dim">unavailable</span>;
const val = (v: number | null, f: (n: number) => string) => (v == null ? NA : f(v));

function Readouts({ frame }: { frame: ViewFrame | null }) {
  useUnitSystem();
  if (!frame) return <p className="p-3 text-xs text-mil-dim">Waiting for a frame…</p>;
  const { ship } = frame;
  const dof = (k: string) => ship.dofs[k] ?? (frame.rm0 ? 'unknown' : 'not supplied');
  return (
    <div className="text-[11px]">
      <Section title="Ship">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          <dt className="text-mil-dim">Time</dt>
          <dd>{frame.tS.toFixed(1)} s{frame.sequence != null && <span className="text-mil-dim"> · seq {frame.sequence}</span>}</dd>
          <dt className="text-mil-dim">Position</dt>
          <dd>{fmt.ft(ship.x_ft, 1)}, {fmt.ft(ship.y_ft, 1)}</dd>
          <dt className="text-mil-dim">Heading</dt>
          <dd>{ship.headingTrueDeg.toFixed(1)}° true</dd>
          <dt className="text-mil-dim">Heave</dt>
          <dd>{ship.heaveMllwFt != null ? `${fmt.ft(ship.heaveMllwFt, 2)} MLLW` : <span className="text-mil-dim">not simulated ({dof('heave')})</span>}</dd>
          <dt className="text-mil-dim">Roll / pitch</dt>
          <dd>{ship.rollDeg != null || ship.pitchDeg != null ? `${ship.rollDeg?.toFixed(1) ?? 'n/a'}° / ${ship.pitchDeg?.toFixed(1) ?? 'n/a'}°` : <span className="text-mil-dim">not simulated</span>}</dd>
          <dt className="text-mil-dim">Surge / sway</dt>
          <dd>{ship.surgeFps != null && ship.swayFps != null ? `${ship.surgeFps.toFixed(2)} / ${ship.swayFps.toFixed(2)} ft/s` : NA}</dd>
          <dt className="text-mil-dim">Acceleration</dt><dd>{ship.surgeFps2 != null && ship.swayFps2 != null ? `${ship.surgeFps2.toFixed(3)} / ${ship.swayFps2.toFixed(3)} ft/s²` : NA}</dd>
          <dt className="text-mil-dim">Rate of turn</dt><dd>{ship.yawDegps == null ? NA : `${ship.yawDegps.toFixed(3)} °/s`}</dd>
        </dl>
        {Object.keys(ship.dofs).length > 0 && (
          <p className="mt-1 text-[10px] text-mil-dim">
            {Object.entries(ship.dofs).map(([k, v]) => `${k}: ${v.replace('_', ' ')}`).join(' · ')}
          </p>
        )}
      </Section>

      <Section title="Forces on the ship">
        {frame.forces.length === 0 ? (
          <p className="text-mil-dim">Not in this frame.</p>
        ) : (
          <table className="w-full">
            <tbody>
              {frame.forces.map((f) => (
                <tr key={f.key}>
                  <td className="pr-2 text-mil-dim">{f.label}</td>
                  <td className="text-right">
                    {f.force ? `${fmt.lbf(f.force.x)}, ${fmt.lbf(f.force.y)}` : f.availability === 'not_simulated' ? <span className="text-mil-dim">not simulated</span> : NA}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-1 text-[9px] text-mil-dim">Vectors are x (along the pier) and y (off the pier).</p>
      </Section>

      <Section title={`Lines (${frame.lines.length})`}>
        {frame.lines.length === 0 ? <p className="text-mil-dim">None.</p> : (
          <ul>
            {frame.lines.map((l) => (
              <li key={l.lineNumber} className="flex justify-between">
                <span>Line {l.lineNumber} <span className="text-mil-dim">{l.status}</span></span>
                <span>{val(l.tensionLbf, fmt.lbf)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Fittings">
        {frame.fittings.length === 0 ? <p className="text-mil-dim">No fitting loads in this frame.</p> : (
          <ul>
            {frame.fittings.map((f) => (
              <li key={`${f.owner}-${f.id}`} className="flex justify-between">
                <span>{f.id} <span className="text-mil-dim">{f.owner}</span></span>
                <span style={f.status ? { color: STATUS_COLOR[f.status] } : undefined}>
                  {val(f.loadLbf, fmt.lbf)}{f.capacityLbf != null ? ` / ${fmt.lbf(f.capacityLbf)}` : ' (no rating)'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Fenders">
        {frame.fenders.length === 0 ? <p className="text-mil-dim">None.</p> : (
          <ul>
            {frame.fenders.map((f) => (
              <li key={f.id} className="flex justify-between">
                <span>{f.id}</span>
                <span style={f.status ? { color: STATUS_COLOR[f.status] } : undefined}>
                  {f.compressionFt != null ? `${fmt.ft(f.compressionFt, 2)} · ${val(f.reactionLbf, fmt.lbf)}` : 'unavailable'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Tugs (${frame.tugs.length})`}>
        {frame.tugs.length === 0 ? <p className="text-mil-dim">None.</p> : (
          <ul>
            {frame.tugs.map((t) => (
              <li key={t.id}>
                <span>{t.id}</span>{' '}
                <span className="text-mil-dim">
                  {t.mode} · {t.contactState.replace('_', ' ')}
                  {t.utilizationPct != null ? ` · ${t.utilizationPct.toFixed(0)}% of capacity` : ''}
                </span>
                <div className="text-mil-dim">
                  {t.actualForce ? `push ${fmt.lbf(Math.hypot(t.actualForce.x, t.actualForce.y))}` : t.legacyForceLbf != null ? `force ${fmt.lbf(t.legacyForceLbf)} (position not supplied)` : 'force unavailable'}
                  {!t.position && ' · tug position/kinematics not modeled'}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Alerts (${frame.alerts.length})`}>
        {frame.alerts.length === 0 ? <p className="text-mil-dim">None in this frame.</p> : (
          <ul className="space-y-1" aria-live="polite" aria-relevant="additions text" aria-label="Alerts in this frame">
            {frame.alerts.map((a, i) => (
              <li key={`${a.code ?? 'text'}-${i}`} style={a.severity ? { color: a.severity === 'RED' ? STATUS_COLOR.RED : a.severity === 'AMBER' ? STATUS_COLOR.AMBER : undefined } : undefined}>
                {a.severity ? `${a.severity}: ` : ''}{a.message}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ChipText({ children, tone }: { children: React.ReactNode; tone?: 'warn' | 'bad' }) {
  return <span className={cn('font-mono text-[10px] uppercase tracking-wider', tone === 'bad' ? 'text-mil-red' : tone === 'warn' ? 'text-mil-amber' : 'text-mil-dim')}>{children}</span>;
}

function LiveControls({ c, s, tugIds, lineNumbers }: { c: MotionController; s: MotionState; tugIds: string[]; lineNumbers: number[] }) {
  const frame = s.frame;
  const [tug, setTug] = useState('');
  const [force, setForce] = useState(5000);
  const [side, setSide] = useState<90 | 270>(90);
  const [line, setLine] = useState<number | ''>('');
  const tugChoices = [...new Set(frame?.tugs.length ? frame.tugs.map((t) => t.id) : tugIds)];
  const lineChoices = [...new Set(frame?.lines.length ? frame.lines.map((l) => l.lineNumber) : lineNumbers)];
  const tugId = tugChoices.includes(tug) ? tug : (tugChoices[0] ?? '');
  const lineNo: number | null = line !== '' && lineChoices.includes(line) ? line : (lineChoices[0] ?? null);
  const connected = s.link === 'open';
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => c.resume()} disabled={!connected} aria-keyshortcuts="Space">Resume</Button>
        <Button size="sm" variant="secondary" onClick={() => c.pause()} disabled={!connected}>Pause</Button>
        <Button size="sm" variant="secondary" onClick={() => c.reset()} disabled={!connected}>Reset</Button>
        <label className="flex items-center gap-1 text-[10px] text-mil-dim" title="Simulated seconds per wall second. The physics time step never changes.">
          Speed
          <select
            className={cn(inputClass, 'h-8 w-20')}
            value={s.speed}
            disabled={!connected}
            aria-label="Session speed"
            onChange={(e) => c.setSpeed(Number(e.target.value))}
          >
            {(LIVE_SPEEDS as readonly number[]).includes(s.speed) ? null : <option value={s.speed}>{s.speed}×</option>}
            {LIVE_SPEEDS.map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
        </label>
        <ChipText tone={s.link === 'open' ? undefined : 'warn'}>link: {s.link}</ChipText>
        <ChipText>session: {s.lifecycle ?? 'state not reported'}</ChipText>
      </div>
      {s.clock && (
        <div className="flex flex-wrap items-center gap-2 text-[10px]" aria-label="Simulation time">
          <ChipText>sim {clockText(s.clock.simS)}</ChipText>
          <ChipText>wall running {clockText(s.clock.wallRunningS)}</ChipText>
          <ChipText>
            {s.clock.effectiveSpeed == null ? 'rate: measuring' : `rate ${s.clock.effectiveSpeed.toFixed(1)}× (asked ${s.speed}×)`}
          </ChipText>
          <ChipText tone={s.clock.forcingTS == null ? 'warn' : undefined}>
            {s.clock.forcingTS == null
              ? 'forcing time: not reported by this simulator'
              : `forcing at t=${s.clock.forcingTS.toFixed(1)} s${s.clock.forcingRevision || s.forcingRevision ? ` · revision ${s.clock.forcingRevision ?? s.forcingRevision}` : ' · no forcing revision'}`}
          </ChipText>
        </div>
      )}
      <div className="flex items-end gap-2">
        <label className="text-[10px] text-mil-dim">
          Tug
          <select className={cn(inputClass, 'h-8 w-24')} value={tugId} onChange={(e) => setTug(e.target.value)} disabled={!tugChoices.length} aria-label="Tug">
            {tugChoices.length === 0 ? <option value="">none assigned</option> : tugChoices.map((id) => <option key={id}>{id}</option>)}
          </select>
        </label>
        <label className="text-[10px] text-mil-dim">
          Force (lbf)
          <input className={cn(inputClass, 'h-8 w-24')} type="number" min={0} step={500} value={force} onChange={(e) => setForce(Number(e.target.value))} />
        </label>
        <label className="text-[10px] text-mil-dim">
          Force toward
          <select className={cn(inputClass, 'h-8 w-28')} value={side} onChange={(e) => setSide(Number(e.target.value) as 90 | 270)}>
            <option value={90}>Starboard (90°)</option>
            <option value={270}>Port (270°)</option>
          </select>
        </label>
        <Button size="sm" onClick={() => tugId && c.tugCommand(tugId, force, side)} disabled={!connected || !tugId} title={tugId ? undefined : 'No tugs are assigned in this layout. Run the planner or assign tugs, then start a new session.'}>Command tug</Button>
      </div>
      <div className="flex items-end gap-2">
        <label className="text-[10px] text-mil-dim">
          Line
          <select className={cn(inputClass, 'h-8 w-20')} value={lineNo ?? ''} onChange={(e) => setLine(Number(e.target.value))} disabled={!lineChoices.length} aria-label="Line">
            {lineChoices.length === 0 ? <option value="">none</option> : lineChoices.map((n) => <option key={n}>{n}</option>)}
          </select>
        </label>
        {(['secured', 'tensioned', 'released'] as const).map((ev) => (
          <Button key={ev} size="sm" variant="secondary" onClick={() => lineNo !== null && c.lineEvent(lineNo, ev)} disabled={!connected || lineNo === null}>{ev}</Button>
        ))}
      </div>
    </div>
  );
}

function ReplayControls({ c, s }: { c: MotionController; s: MotionState }) {
  const rec = s.recording;
  if (!rec) return null;
  const start = rec.frames[0].t_s;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button size="sm" onClick={() => (s.playing ? c.pauseReplay() : c.play())} aria-keyshortcuts="Space">{s.playing ? 'Pause' : 'Play'}</Button>
      <input
        type="range"
        aria-label="Scrub the recording"
        className="min-w-[220px] flex-1"
        min={start}
        max={rec.durationS}
        step={0.5}
        value={Math.min(s.cursorS, rec.durationS)}
        aria-valuetext={`${s.cursorS.toFixed(1)} of ${rec.durationS.toFixed(0)} seconds`}
        onChange={(e) => c.seek(Number(e.target.value))}
      />
      <span className="w-28 text-right font-mono text-[11px]">{s.cursorS.toFixed(1)} / {rec.durationS.toFixed(0)} s</span>
      <label className="flex items-center gap-1 text-[10px] text-mil-dim">
        Speed
        <select className={cn(inputClass, 'h-8 w-20')} value={s.speed} onChange={(e) => c.setSpeed(Number(e.target.value))}>
          {REPLAY_SPEEDS.map((v) => <option key={v} value={v}>{v}×</option>)}
        </select>
      </label>
      <ChipText>{rec.label}</ChipText>
    </div>
  );
}

export function MotionView({ controller: c, workspace = false }: { controller: MotionController; workspace?: boolean }) {
  useUnitSystem();
  const s = c.state.use((x) => x);
  const [offset, setOffset] = useState(120);
  const [detailsOpen, setDetailsOpen] = useState(true);
  const [shipViewsOpen, setShipViewsOpen] = useState(true);
  const [canvasView, setCanvasView] = useState<'plan' | 'satellite' | 'street' | SectionView>('satellite');
  const [flow, setFlow] = useState<FlowDisplay>({ wind: true, current: true, animate: typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? !window.matchMedia('(prefers-reduced-motion: reduce)').matches : false });
  const [vectors, setVectors] = useState(true);
  const [headerHeight, setHeaderHeight] = useState(40);
  useEffect(() => {
    if (!workspace) return;
    const header = document.querySelector('header');
    if (!header) return;
    const measure = () => setHeaderHeight(header.getBoundingClientRect().height || 40);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure); observer.observe(header);
    return () => observer.disconnect();
  }, [workspace]);
  useEffect(() => workspace ? c.bindWorkspaceView() : undefined, [c, workspace]);
  const face = s.scene?.face_bearing_true_deg ?? DEFAULT_FACE_BEARING;
  const map = !workspace && s.view === 'map';
  const section = workspace && ['forward', 'aft', 'side'].includes(canvasView) ? canvasView as SectionView : null;
  const basemap: BasemapKind = workspace && (canvasView === 'satellite' || canvasView === 'street') ? canvasView : 'schematic';
  const dialogRef = useRef<HTMLDivElement>(null);
  // The full-screen plan view is modal: move focus into it so keyboard and screen-reader users start inside it.
  useEffect(() => {
    if (!map) dialogRef.current?.focus();
  }, [map]);
  const waterFt = s.frame ? drawableWaterLevelFt(s.frame) : null;
  const announcement = [
    `Frame validity ${s.frame?.badge.validity ?? 'no frame'}`,
    `provenance ${s.frame?.badge.provenance ?? 'unknown'}`,
    `link ${s.link}`,
    `session ${s.lifecycle ?? 'state not reported'}`,
  ].join(', ');

  // Keyboard: space toggles run/pause, r resets, Escape closes. Ignored while typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      // Escape closes from anywhere except an open list or a text area; the other shortcuts are ignored in fields.
      if (e.key === 'Escape') {
        if (e.defaultPrevented || (t && (t.tagName === 'SELECT' || t.tagName === 'TEXTAREA'))) return;
        if (workspace) setDetailsOpen(false);
        else c.close();
        return;
      }
      if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.tagName === 'BUTTON')) return;
      if (e.key === ' ') {
        e.preventDefault();
        if (c.s.source === 'recording') {
          if (c.s.playing) c.pauseReplay();
          else c.play();
        } else if (c.s.source === 'live') {
          if (c.s.lifecycle === 'running') c.pause();
          else c.resume();
        }
      } else if (e.key === 'r' && c.s.source === 'live') c.reset();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [c, workspace]);

  return (
    <div
      className={cn('flex flex-col outline-none', workspace ? 'pointer-events-auto fixed inset-x-0 bottom-0 top-10 z-40 bg-mil-bg' : map ? 'pointer-events-none absolute inset-0 z-20' : 'pointer-events-auto fixed inset-0 z-50 bg-mil-bg')}
      role="dialog"
      aria-modal={!workspace && !map}
      aria-label="Motion view"
      tabIndex={-1}
      ref={dialogRef}
      style={workspace ? { top: headerHeight, '--motion-top': `${headerHeight}px` } as React.CSSProperties : undefined}
    >
      {/* Announces only when validity, provenance, link or session state changes, not on every frame. */}
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <div className="pointer-events-auto flex flex-wrap items-center justify-between gap-3 border-b border-mil-border bg-mil-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <div><span className="mil-label">{workspace ? 'Maneuvering workspace' : 'Motion view'}</span>{workspace && <p className="mt-0.5 text-[9px] text-mil-dim">Demonstrator · not navigational guidance</p>}</div>
          {workspace ? <><ScenarioSelector c={c} s={s} /><div className="flex items-center gap-1 border-l border-mil-border pl-3"><Button size="sm" disabled={s.source !== 'live' || s.link !== 'open' || s.busy || s.stateImportBusy || s.lifecycleInvalid} onClick={() => s.lifecycle === 'running' ? c.pause() : c.resume()} aria-keyshortcuts="Space">{s.lifecycle === 'running' ? 'Pause' : s.frame && s.frame.tS > 0 ? 'Resume' : 'Start'}</Button><Button size="sm" variant="secondary" disabled={s.source !== 'live' || s.link !== 'open'} onClick={() => c.reset()}>Reset</Button><select aria-label="Simulation speed" className={`${inputClass} h-8 w-16`} disabled={s.source !== 'live' || s.link !== 'open'} value={s.speed} onChange={(e) => c.setSpeed(Number(e.target.value))}>{LIVE_SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}×</option>)}</select></div></> : <>
          <Button size="sm" onClick={() => void c.startSession(offset)} disabled={s.busy}>{s.source === 'live' ? 'Restart session' : 'Start session'}</Button>
          <label className="flex items-center gap-1 text-[10px] text-mil-dim" title="How far off the berth the ship starts. A demo default, not a recommended approach.">
            Start offset
            <input className={cn(inputClass, 'h-8 w-16')} type="number" min={20} step={10} value={offset} onChange={(e) => setOffset(Number(e.target.value))} />
            ft
          </label>
          <Button size="sm" variant="secondary" onClick={() => void c.loadRecording()} disabled={s.busy}>Replay recording</Button>
          {s.sessionRecordings.length > 0 && (
            <select
              className={cn(inputClass, 'h-8 w-48')}
              aria-label="Session recordings"
              value=""
              disabled={s.busy}
              onChange={(e) => e.target.value && void c.loadSessionRecording(e.target.value)}
            >
              <option value="">Session recordings…</option>
              {s.sessionRecordings.map((r) => (
                <option key={r.sessionId} value={r.sessionId}>
                  {r.startedAt.slice(11, 19)}Z · {r.sessionId}
                </option>
              ))}
            </select>
          )}
          </>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="View" className="flex">
            {workspace ? ([['plan', 'Plan'], ['satellite', 'Satellite'], ['street', 'Map'], ['forward', 'Forward'], ['aft', 'Aft'], ['side', 'Side']] as const).map(([id, label]) => <button key={id} aria-pressed={canvasView === id} onClick={() => setCanvasView(id)} className={cn('h-8 border px-2 font-mono text-[10px] uppercase tracking-wider', canvasView === id ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan' : 'border-mil-border text-mil-text hover:text-white')}>{label}</button>) : (['plan', 'map'] as const).map((v) => (
              <button
                key={v}
                aria-pressed={s.view === v}
                onClick={() => c.setView(v)}
                className={cn('h-8 border px-3 font-mono text-[10px] uppercase tracking-wider', s.view === v ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan' : 'border-mil-border text-mil-text hover:text-white')}
              >
                {v === 'plan' ? 'Plan' : 'Map 2D/3D'}
              </button>
            ))}
          </div>
          {map && (
            <div role="group" aria-label="Camera" className="flex">
              {([['top', 'Top'], ['bow', 'Bow'], ['portQuarter', 'Port quarter'], ['pierSide', 'Pier side']] as const).map(([id, label]) => (
                <button key={id} onClick={() => c.setCamera(id)} className="h-8 border border-mil-border px-2 font-mono text-[10px] uppercase tracking-wider text-mil-text hover:text-white">
                  {label}
                </button>
              ))}
            </div>
          )}
          {workspace && !section && <Button size="sm" variant="secondary" onClick={() => setShipViewsOpen(!shipViewsOpen)} aria-expanded={shipViewsOpen} aria-controls="motion-ship-views">{shipViewsOpen ? 'Hide ship views' : 'Show ship views'}</Button>}
          <Button size="sm" variant="secondary" onClick={() => setDetailsOpen(!detailsOpen)} aria-expanded={detailsOpen} aria-controls="motion-readouts">{detailsOpen ? 'Hide details' : 'Show details'}</Button>
          {!workspace && <Button size="sm" variant="ghost" onClick={() => c.close()} aria-keyshortcuts="Escape">Close</Button>}
        </div>
      </div>

      <div className={cn('border-b border-mil-border px-3 py-2', map ? 'pointer-events-auto bg-mil-panel/95' : '')}><Badges frame={s.frame} state={s} /></div>

      {workspace && <div className="flex flex-wrap items-center justify-between gap-2 border-b border-mil-border bg-mil-bg px-3 py-1.5 text-[10px]">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1"><span className={s.lifecycle === 'running' ? 'text-mil-cyan' : 'text-mil-amber'}>{s.busy ? 'LOADING PAUSED SCENARIO' : (s.lifecycle ?? 'PAUSED').toUpperCase()} · {s.frame?.tS.toFixed(1) ?? '—'} s</span><span className="text-mil-text">{s.workspace?.ship.name ?? 'Vessel not yet loaded'}</span><span className="text-mil-dim">{s.workspace?.berth.name}</span>{s.frame && <span>Heading {s.frame.ship.headingTrueDeg.toFixed(1)}° T · surge {s.frame.ship.surgeFps?.toFixed(2) ?? '—'} ft/s · sway {s.frame.ship.swayFps?.toFixed(2) ?? '—'} ft/s</span>}</div>
        <div className="flex flex-wrap gap-3" role="group" aria-label="Display layers"><label className="flex items-center gap-1"><input type="checkbox" checked={s.predictionEnabled} onChange={(e) => c.setPredictionEnabled(e.target.checked)} />Prediction</label><label className="flex items-center gap-1"><input type="checkbox" checked={vectors} onChange={(e) => setVectors(e.target.checked)} />Vectors</label>{(['wind', 'current', 'animate'] as const).map((key) => <label key={key} className="flex items-center gap-1"><input type="checkbox" checked={flow[key]} onChange={(e) => setFlow({ ...flow, [key]: e.target.checked })} />{key === 'animate' ? 'Animate flow' : key === 'wind' ? 'Wind' : 'Current'}</label>)}</div>
      </div>}

      {(s.error || s.notice || s.sceneError || s.lifecycleMessage || s.lifecycleReasons.length > 0) && (
        <div className={cn('space-y-1 border-b border-mil-border px-3 py-1 text-[11px]', map ? 'pointer-events-auto bg-mil-panel/95' : '')}>
          {s.error && <p role="alert" className="text-mil-red">{s.error}</p>}
          {s.notice && <p role="status" className="text-mil-amber">{s.notice}</p>}
          {s.sceneError && <p role="status" className="text-mil-dim">{s.sceneError}</p>}
          {s.lifecycleMessage && <p role="status" className="text-mil-dim">Session: {s.lifecycleMessage}</p>}
          {s.lifecycleReasons.length > 0 && <details open={s.lifecycleInvalid || !workspace}><summary className={s.lifecycleInvalid ? 'cursor-pointer text-mil-red' : 'cursor-pointer text-mil-amber'}>{s.lifecycleReasons.length} model limitations · {s.lifecycleInvalid ? 'invalid state' : 'limited, unqualified demonstration'}</summary><ul role={s.lifecycleInvalid ? 'alert' : 'status'} className={s.lifecycleInvalid ? 'text-mil-red' : 'text-mil-amber'}>
            {s.lifecycleReasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul></details>}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className={cn('relative min-w-0 flex-1', map && 'pointer-events-none')}>
          {workspace && !section && <div className={cn('pointer-events-auto absolute left-3 top-3 z-10 rounded-sm border border-mil-amber/30 bg-mil-panel/95 p-2 text-[10px] text-mil-amber', detailsOpen ? 'max-w-[40%]' : 'max-w-[55%]')} aria-label="Prediction coverage">
            <p className={cn('font-semibold uppercase tracking-wider', s.prediction?.validity.state === 'invalid' && 'text-mil-red')}>{s.predictionWhatIf ? 'What-if order preview' : 'Backup camera'} · {s.prediction?.validity.state ?? 'unavailable'}{s.prediction && ` · ${s.prediction.horizon_s.toFixed(0)} s${s.prediction.complete ? '' : ' TRUNCATED'}`}</p>
            {s.prediction ? <details open={detailsOpen}><summary className="cursor-pointer text-[9px]">Unchecked: {s.prediction.hazards_unchecked.join(', ') || 'coverage not qualified'} · uncertainty unavailable · forecast details{s.prediction.warnings.some((w) => w.severity === 'RED') && ' / RED warning'}</summary><div className="mt-1 space-y-1"><p>{s.prediction.horizon_s.toFixed(0)} s returned · snapshot t={s.prediction.source.t_s.toFixed(1)} s{s.frame && ` · age ${Math.max(0, s.frame.tS - s.prediction.source.t_s).toFixed(1)} sim s`}</p><p>{s.prediction.complete ? 'Deterministic footprints' : 'TRUNCATED prediction'}</p>{s.prediction.warnings.map((w) => <p key={`${w.code}-${w.t_s}`} className={w.severity === 'RED' ? 'text-mil-red' : ''}>{w.message}</p>)}</div></details> : <p>{s.predictionError ?? (s.predictionEnabled ? 'Waiting for a backend prediction. Hazard coverage is unknown.' : 'Prediction display off. Hazard coverage is unknown.')}</p>}
            {s.predictionError && s.prediction && <p role="status" className="mt-1 text-mil-amber">Refresh unavailable: {s.predictionError} Showing the last snapshot within its returned horizon.</p>}
            {s.predictionWhatIf && <Button size="sm" variant="secondary" className="mt-2" onClick={() => { c.setPredictionEnabled(false); c.setPredictionEnabled(true); }}>Return to current orders</Button>}
          </div>}
          {section ? <SectionViews s={s} view={section} /> : map ? (
            <div role="status" className="pointer-events-none absolute bottom-2 left-3 max-w-[70%] rounded-sm border border-mil-border bg-mil-panel/85 p-2 text-[10px] text-mil-dim">
              {s.frame ? (
                <>
                  <p>Map view draws position, heading, and heave, roll and pitch when the frame supplies them. Drag to pan; in 3D, drag to orbit.</p>
                  {waterFt != null && <p className="mt-0.5">Water surface drawn at {fmt.ft(waterFt, 1)} MLLW from the frame: display only, not a simulated free surface.</p>}
                  {s.notDrawn.length > 0 && <p className="mt-0.5">Not drawn: {s.notDrawn.join(', ')}.</p>}
                </>
              ) : (
                <p>The map shows the planning layout until a frame arrives.</p>
              )}
            </div>
          ) : s.source === 'none' && !s.busy ? (
            <div className="flex h-full items-center justify-center p-8 text-center text-xs text-mil-dim">
              <div>
                <p className="text-sm text-mil-text">Nothing running.</p>
                <p className="mt-2">Start a session from the current berth and ship, or replay the recorded mock fixture.<br />Nothing in this view is invented: values the simulator does not supply show as unavailable.</p>
              </div>
            </div>
          ) : s.busy && !s.frame ? (
            <div className="flex h-full items-center justify-center text-xs text-mil-cyan" role="status">Loading…</div>
          ) : !s.frame ? (
            <div className="flex h-full items-center justify-center p-8 text-center text-xs text-mil-dim" role="status">
              {s.link === 'open' ? 'Connected. Waiting for the first frame; press Resume to run.' : s.link === 'connecting' ? 'Connecting to the session…' : 'No frame yet.'}
            </div>
          ) : (
            <>
              <MotionCanvas frame={s.frame} scene={s.scene} trail={s.trail} faceBearingDeg={face} basemap={basemap} origin={s.workspace ? { lat: s.workspace.berth.origin_lat, lon: s.workspace.berth.origin_lon, bearingDeg: face } : null} flow={workspace ? flow : undefined} vectors={vectors} prediction={s.predictionEnabled ? s.prediction : null} predictionWhatIf={s.predictionWhatIf} shipClass={s.workspace?.ship} route={s.workspace?.route} compactHud={workspace && !detailsOpen} animateMotion={s.source === 'live' && s.link === 'open' && s.lifecycle === 'running' && !s.lifecycleInvalid} />
              {s.source === 'live' && s.droppedForDisplay > 0 && (
                <p className="pointer-events-none absolute bottom-2 left-3 text-[10px] text-mil-dim">Showing the newest frame; {s.droppedForDisplay} older frames arrived faster than they could be drawn and were skipped.</p>
              )}
            </>
          )}
        </div>
        {detailsOpen && <aside id="motion-readouts" className={cn('w-[320px] max-w-[40vw] shrink-0 overflow-y-auto border-l border-mil-border', map ? 'pointer-events-auto bg-mil-panel/95' : 'bg-mil-panel/60')} aria-label="Frame readouts">
          {workspace && <Section title="Source and playback"><StateSourcePanel c={c} s={s} /><details className="mt-2 text-[10px]"><summary className="cursor-pointer text-mil-cyan">Recordings and planner setup</summary><div className="mt-2 space-y-2"><Button size="sm" variant="secondary" disabled={s.busy} onClick={() => void c.loadRecording()}>Replay recorded mock fixture</Button>{s.sessionRecordings.map((r) => <button className="block text-mil-cyan underline" key={r.sessionId} onClick={() => void c.loadSessionRecording(r.sessionId)}>Replay {r.startedAt.slice(11, 19)}Z · {r.sessionId.slice(-10)}</button>)}<label className="flex items-center gap-2">Start offset (ft)<input aria-label="Planner start offset (ft)" className={`${inputClass} w-20`} type="number" min={20} value={offset} onChange={(e) => setOffset(Number(e.target.value))} /></label><Button size="sm" variant="secondary" disabled={s.busy} onClick={() => void c.startSession(offset)}>Load planner setup paused</Button></div></details></Section>}
          {workspace && s.frame?.guidance && <Section title="Route following"><div className="space-y-1 text-[10px]"><p className="text-mil-amber">{s.frame.guidance.completed && s.frame.guidance.active ? 'Holding point reached; synthetic holding active' : s.frame.guidance.active ? 'Synthetic route controller active' : 'Synthetic controller inactive / manual override'}</p><p>Waypoint {s.frame.guidance.waypoint_index + 1}: {s.frame.guidance.waypoint_name}</p><p>Target {s.frame.guidance.target_speed_kt.toFixed(1)} kt · cross-track {s.frame.guidance.cross_track_ft.toFixed(0)} ft</p><p>Remaining {s.frame.guidance.remaining_ft.toFixed(0)} ft</p><p className="text-mil-dim">Applying a manual helm order disables route following and holding. Route tracking does not establish hazard clearance.</p></div></Section>}
          {s.frame && <EnvironmentGlyph frame={s.frame} faceBearingDeg={face} />}
          {workspace && <p className="border-b border-mil-border px-3 py-2 text-[9px] text-mil-dim">Flow texture uses simulation time and supplied wind/current direction. Particle speed is a display scale, not a force or forecast.</p>}
          <Readouts frame={s.frame} />
        </aside>}
      </div>

      {workspace && shipViewsOpen && !section && <section id="motion-ship-views" aria-label="Ship views" className="grid h-[18vh] max-h-[180px] min-h-[112px] shrink-0 grid-cols-3 divide-x divide-mil-border border-t border-mil-border">
        {(['forward', 'aft', 'side'] as const).map((view) => <div key={view} className="min-h-0 min-w-0 overflow-hidden"><SectionViews s={s} view={view} compact /></div>)}
      </section>}

      <div className={cn('pointer-events-auto max-h-[45vh] shrink-0 overflow-y-auto border-t border-mil-border bg-mil-panel', !s.workspace && 'px-3 py-2')}>
        {s.source === 'live' && s.workspace ? <ManeuverControls key={`${s.sessionId}:${s.frame?.runId}`} c={c} s={s} /> : s.source === 'live' ? <LiveControls c={c} s={s} tugIds={c.tugIds()} lineNumbers={c.lineNumbers()} /> : s.source === 'recording' ? <ReplayControls c={c} s={s} /> : <p className="text-[11px] text-mil-dim">Controls appear once a session or recording is loaded. Space plays or pauses, R resets a live session{workspace ? ', Esc hides details.' : ', Esc closes.'}</p>}
      </div>
    </div>
  );
}
