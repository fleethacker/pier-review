import { useEffect, useState } from 'react';
import { cn } from '../../../lib/cn';
import { STATUS_COLOR } from '../../../shell/theme';
import { Button, inputClass } from '../../../shell/ui';
import { fmt, useUnitSystem } from '../units';
import { DEFAULT_FACE_BEARING } from './frames';
import type { Badge, ValidityState, ViewFrame } from './frames';
import type { MotionController, MotionState } from './controller';
import { REPLAY_SPEEDS } from './controller';
import { EnvironmentGlyph, MotionCanvas } from './MotionCanvas';

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
        environment: {env ? `${sourceText ?? 'source not stated'}${ageS != null ? `, ${ageS.toFixed(0)} s old` : ', age not stated'}` : 'not in frame'}
      </Pill>
      <Pill color={state.source === 'live' ? '#00e5ff' : '#a78bfa'}>{state.source === 'live' ? 'live session' : state.source === 'recording' ? 'replay' : 'idle'}</Pill>
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
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Alerts (${frame.alerts.length})`}>
        {frame.alerts.length === 0 ? <p className="text-mil-dim">None in this frame.</p> : (
          <ul className="space-y-1">
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
        <label className="flex items-center gap-1 text-[10px] text-mil-dim" title="The session protocol has pause, resume and reset only; speed cannot be changed on a live session.">
          Speed
          <select className={cn(inputClass, 'h-8 w-28')} disabled aria-label="Speed (fixed for live sessions)">
            <option>1× fixed</option>
          </select>
        </label>
        <ChipText tone={s.link === 'open' ? undefined : 'warn'}>link: {s.link}</ChipText>
        <ChipText>session: {s.lifecycle ?? 'state not reported'}</ChipText>
      </div>
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
          Push from
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

export function MotionView({ controller: c }: { controller: MotionController }) {
  useUnitSystem();
  const s = c.state.use((x) => x);
  const [offset, setOffset] = useState(120);
  const face = s.scene?.face_bearing_true_deg ?? DEFAULT_FACE_BEARING;

  // Keyboard: space toggles run/pause, r resets, Escape closes. Ignored while typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA' || t.tagName === 'BUTTON')) return;
      if (e.key === 'Escape') c.close();
      else if (e.key === ' ') {
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
  }, [c]);

  return (
    <div className="pointer-events-auto fixed inset-0 z-50 flex flex-col bg-mil-bg" role="dialog" aria-label="Motion view">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-mil-border bg-mil-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="mil-label">Motion view</span>
          <Button size="sm" onClick={() => void c.startSession(offset)} disabled={s.busy}>{s.source === 'live' ? 'Restart session' : 'Start session'}</Button>
          <label className="flex items-center gap-1 text-[10px] text-mil-dim" title="How far off the berth the ship starts. A demo default, not a recommended approach.">
            Start offset
            <input className={cn(inputClass, 'h-8 w-16')} type="number" min={20} step={10} value={offset} onChange={(e) => setOffset(Number(e.target.value))} />
            ft
          </label>
          <Button size="sm" variant="secondary" onClick={() => void c.loadRecording()} disabled={s.busy}>Replay recording</Button>
        </div>
        <Button size="sm" variant="ghost" onClick={() => c.close()} aria-keyshortcuts="Escape">Close</Button>
      </div>

      <div className="border-b border-mil-border px-3 py-2"><Badges frame={s.frame} state={s} /></div>

      {(s.error || s.notice || s.sceneError || s.lifecycleMessage) && (
        <div className="space-y-1 border-b border-mil-border px-3 py-1 text-[11px]">
          {s.error && <p role="alert" className="text-mil-red">{s.error}</p>}
          {s.notice && <p role="status" className="text-mil-amber">{s.notice}</p>}
          {s.sceneError && <p className="text-mil-dim">{s.sceneError}</p>}
          {s.lifecycleMessage && <p className="text-mil-dim">Session: {s.lifecycleMessage}</p>}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {s.source === 'none' && !s.busy ? (
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
              <MotionCanvas frame={s.frame} scene={s.scene} trail={s.trail} faceBearingDeg={face} />
              {s.source === 'live' && s.droppedForDisplay > 0 && (
                <p className="pointer-events-none absolute bottom-2 left-3 text-[10px] text-mil-dim">Showing the newest frame; {s.droppedForDisplay} older frames arrived faster than they could be drawn and were skipped.</p>
              )}
            </>
          )}
        </div>
        <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-mil-border bg-mil-panel/60" aria-label="Frame readouts">
          {s.frame && <EnvironmentGlyph frame={s.frame} faceBearingDeg={face} />}
          <Readouts frame={s.frame} />
        </aside>
      </div>

      <div className="border-t border-mil-border bg-mil-panel px-3 py-2">
        {s.source === 'live' ? <LiveControls c={c} s={s} tugIds={c.tugIds()} lineNumbers={c.lineNumbers()} /> : s.source === 'recording' ? <ReplayControls c={c} s={s} /> : <p className="text-[11px] text-mil-dim">Controls appear once a session or recording is loaded. Space plays or pauses, R resets a live session, Esc closes.</p>}
      </div>
    </div>
  );
}
