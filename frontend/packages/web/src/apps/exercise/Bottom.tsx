import { useState } from 'react';
import { cn } from '../../lib/cn';
import { Button } from '../../shell/ui';
import { useClockSecond, useController, useExercise } from './context';
import { PLAYBACK_RATES } from './controller';
import { bearingTo, distanceM, formatClock, formatLatLon, mToNm } from './geo';
import { SHIP_CLASSES, SIDE_COLORS } from './ships';
import { unitHp, statesAt } from './sim';
import { EVENT_COLOR, STATUS_COLOR, STATUS_LABEL, eventFocus, eventText, unitStatus } from './status';

const bearing = (deg: number) => `${Math.round(deg).toString().padStart(3, '0')}°`;

function PlaybackBar() {
  const c = useController();
  const second = useClockSecond();
  const playing = useExercise((s) => s.playing);
  const rate = useExercise((s) => s.rate);
  const duration = useExercise((s) => s.active.scenario.durationS);
  const events = useExercise((s) => s.active.trajectory.events);
  return (
    <div className="flex items-center gap-3 border-b border-mil-border px-3 py-2">
      <Button size="sm" aria-label={playing ? 'Pause' : 'Play'} onClick={() => c.togglePlay()} className="w-16">
        {playing ? 'Pause' : 'Play'}
      </Button>
      <Button size="sm" variant="secondary" aria-label="Restart" onClick={() => c.restart()}>
        Restart
      </Button>
      <span className="mil-value w-28 text-sm" aria-label="Elapsed time">
        T+{formatClock(second)}
      </span>
      <div className="relative min-w-0 flex-1">
        <input
          type="range"
          aria-label="Time"
          className="w-full"
          min={0}
          max={duration}
          step={1}
          value={second}
          onChange={(e) => c.seek(Number(e.target.value))}
        />
        {/* Ticks on the timeline where something happened, so you can see where to look. */}
        <div className="pointer-events-none absolute inset-x-1.5 top-full -mt-1 h-1.5" aria-hidden>
          {events
            .filter((e) => e.type === 'hit' || e.type === 'mine' || e.type === 'destroyed' || e.type === 'intercept')
            .map((e, i) => (
              <span key={i} className="absolute top-0 h-1.5 w-px" style={{ left: `${(e.tS / duration) * 100}%`, background: EVENT_COLOR[e.type] }} />
            ))}
        </div>
      </div>
      <span className="mil-value w-24 text-right text-xs text-mil-dim">{formatClock(duration)}</span>
      <label className="flex items-center gap-2">
        <span className="mil-label">Speed</span>
        <select
          aria-label="Playback speed"
          className="rounded-sm border border-mil-border bg-mil-bg px-2 py-1 font-mono text-xs text-white"
          value={rate}
          onChange={(e) => c.setRate(Number(e.target.value))}
        >
          {PLAYBACK_RATES.map((r) => (
            <option key={r} value={r}>
              {r}×
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

const HEAD = 'px-3 py-1.5 text-left text-[9px] font-medium uppercase tracking-widest text-mil-dim';

function Contacts() {
  const c = useController();
  const second = useClockSecond();
  const run = useExercise((s) => s.active);
  const selectedId = useExercise((s) => s.selectedId);
  const states = statesAt(run.trajectory, second);
  const ref = states[run.trajectory.unitIds.indexOf(selectedId ?? '')];
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 bg-mil-panel">
          <tr>
            <th className={HEAD}>Ship</th>
            <th className={HEAD}>Class</th>
            <th className={HEAD}>Status</th>
            <th className={HEAD}>HP</th>
            <th className={HEAD}>Hdg</th>
            <th className={HEAD}>STW kt</th>
            <th className={HEAD}>SOG kt</th>
            <th className={HEAD}>Alt m</th>
            <th className={HEAD}>Position</th>
            <th className={HEAD}>{ref ? 'Rng nm / Brg from selected' : 'Rng / Brg'}</th>
          </tr>
        </thead>
        <tbody>
          {run.scenario.units.map((u, i) => {
            const st = states[i];
            const selected = u.id === selectedId;
            const cls = SHIP_CLASSES[u.classId];
            const status = unitStatus(u, st, second, run.trajectory.events);
            const live = st.active;
            const dash = '–';
            return (
              <tr
                key={u.id}
                onClick={() => c.select(selected ? null : u.id)}
                className={cn('cursor-pointer border-t border-mil-border/50', selected ? 'bg-mil-cyan/10 text-white' : 'text-mil-text hover:text-white', !live && 'opacity-60')}
              >
                <td className="px-3 py-1">
                  <span className="mr-2 inline-block h-2 w-2 rounded-full align-middle" style={{ background: SIDE_COLORS[u.side] }} />
                  {u.name}
                </td>
                <td className="px-3 py-1">{cls.id}</td>
                <td className={cn('px-3 py-1', STATUS_COLOR[status])}>{STATUS_LABEL[status]}</td>
                <td className="px-3 py-1 tabular-nums">{!cls.weapon && cls.domain !== 'static' && live ? `${Math.round(st.hp)}/${unitHp(u)}` : dash}</td>
                <td className="px-3 py-1 tabular-nums">{live ? bearing(st.headingDeg) : dash}</td>
                <td className="px-3 py-1 tabular-nums">{live ? st.speedKt.toFixed(1) : dash}</td>
                <td className="px-3 py-1 tabular-nums">{live ? st.sogKt.toFixed(1) : dash}</td>
                <td className="px-3 py-1 tabular-nums">{live && cls.domain === 'air' ? Math.round(st.altM).toLocaleString('en-US') : dash}</td>
                <td className="px-3 py-1 tabular-nums">{live ? formatLatLon(st) : dash}</td>
                <td className="px-3 py-1 tabular-nums">
                  {ref?.active && live && !selected ? `${mToNm(distanceM(ref, st)).toFixed(2)} / ${bearing(bearingTo(ref, st))}` : dash}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Events() {
  const c = useController();
  const second = useClockSecond();
  const run = useExercise((s) => s.active);
  const events = run.trajectory.events;
  const name = (id: string) => run.scenario.units.find((u) => u.id === id)?.name ?? id;
  if (events.length === 0) {
    return <p className="p-4 text-[11px] text-mil-dim">Nothing happens in this run: no launches, hits, interceptions or mines. Add a missile or a mine to see events here.</p>;
  }
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <ul aria-label="Events" className="text-[11px]">
        {events.map((e, i) => {
          const past = e.tS <= second;
          return (
            <li key={i}>
              <button
                onClick={() => {
                  c.seek(Math.max(0, e.tS - 8));
                  const focus = eventFocus(e, run.scenario.units);
                  if (focus) c.select(focus);
                }}
                className={cn('flex w-full items-center gap-3 border-t border-mil-border/50 px-3 py-1 text-left hover:text-white', past ? 'text-mil-text' : 'text-mil-dim')}
              >
                <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: EVENT_COLOR[e.type] }} />
                <span className="mil-value w-20 shrink-0 tabular-nums">T+{formatClock(e.tS)}</span>
                <span className="min-w-0 flex-1 truncate">{eventText(e, name)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Bottom() {
  const [tab, setTab] = useState<'contacts' | 'events'>('contacts');
  const eventCount = useExercise((s) => s.active.trajectory.events.length);
  return (
    <div className="flex h-full flex-col">
      <PlaybackBar />
      <div role="tablist" aria-label="Details" className="flex gap-4 border-b border-mil-border px-3">
        {(['contacts', 'events'] as const).map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn('border-b-2 py-1.5 font-mono text-[10px] uppercase tracking-wider', tab === id ? 'border-mil-cyan text-mil-cyan' : 'border-transparent text-mil-text hover:text-white')}
          >
            {id === 'contacts' ? 'Contacts' : `Events (${eventCount})`}
          </button>
        ))}
      </div>
      {tab === 'contacts' ? <Contacts /> : <Events />}
    </div>
  );
}
