import { useEffect, useRef } from 'react';
import { cn } from './lib/cn';
import { useClockSecond, useController, useExercise } from './context';
import { formatClock, formatLatLon } from './geo';
import { SHIP_CLASSES, SIDE_COLORS } from './ships';
import { unitHp, unitStateAt } from './sim';
import { EVENT_COLOR, STATUS_LABEL, eventFocus, eventText, unitStatus } from './status';
import { scrollIntoViewSafely } from './storyboard';

/**
 * The right-hand rail: what the selected unit is doing, and under it everything that has happened, arriving as the clock
 * reaches it. This is the feed a storyboard is built from, so every line carries the two things wanted next — the unit it
 * is about, and the collected record it came from.
 */

function SelectedReadout() {
  const second = useClockSecond();
  const c = useController();
  const unit = useExercise((s) => s.active.scenario.units.find((u) => u.id === s.selectedId) ?? null);
  const run = useExercise((s) => s.active);
  if (!unit) {
    return (
      <p className="shrink-0 border-b border-mil-border px-3 py-2 text-[11px] text-mil-dim">
        Click a ship on the map or an event below to see its readout.
      </p>
    );
  }
  const i = run.trajectory.unitIds.indexOf(unit.id);
  const st = unitStateAt(run.trajectory, i, second);
  const cls = SHIP_CLASSES[unit.classId];
  const status = unitStatus(unit, st, second, run.trajectory.events);
  const rows: [string, string][] = [
    ['Class', cls.name],
    ['Status', STATUS_LABEL[status]],
    ...(!cls.weapon && cls.domain !== 'static' ? ([['Hit points', `${Math.round(st.hp)} / ${unitHp(unit)}`]] as [string, string][]) : []),
    ['Length / beam', `${cls.loaM} / ${cls.beamM} m`],
    ['Position', formatLatLon(st)],
    ['Heading', `${Math.round(st.headingDeg).toString().padStart(3, '0')}°T`],
    ['Speed through water', `${st.speedKt.toFixed(1)} kt`],
    ['Course / speed over ground', `${Math.round(st.cogDeg).toString().padStart(3, '0')}°T / ${st.sogKt.toFixed(1)} kt`],
    ...(cls.domain === 'air' ? ([['Altitude', `${Math.round(st.altM).toLocaleString('en-US')} m`]] as [string, string][]) : []),
    ...(cls.domain === 'sub' ? ([['Depth', `${Math.round(-st.altM)} m`]] as [string, string][]) : []),
    ...((unit.decoys ?? 0) > 0 ? ([['Decoys', `${unit.decoys}`]] as [string, string][]) : []),
    ...(unit.signature !== undefined ? ([['Radar signature', `${unit.signature}× normal`]] as [string, string][]) : []),
    ...(cls.sensorRangeNm > 0 ? ([['Sensor range', `${cls.sensorRangeNm} nm (illustrative)`]] as [string, string][]) : []),
    ...(cls.weapon
      ? ([
          ['Damage', `${unit.damage ?? cls.weapon.damage}`],
          ['Hit chance', `${Math.round((unit.pHit ?? cls.weapon.pHit) * 100)}%`],
        ] as [string, string][])
      : []),
    ...(cls.defence
      ? ([['Defence', `${Math.round((unit.pKill ?? cls.defence.pKill) * 100)}% per shot, ${(cls.defence.rangeM / 1000).toFixed(0)} km`]] as [string, string][])
      : []),
  ];
  return (
    <div className="max-h-[45%] shrink-0 overflow-y-auto border-b border-mil-border bg-mil-bg/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-sm text-white">
          <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SIDE_COLORS[unit.side] }} />
          <span className="truncate">{unit.name}</span>
        </span>
        <button className="shrink-0 text-[10px] uppercase tracking-wider text-mil-dim hover:text-white" onClick={() => c.select(null)}>
          Clear selection
        </button>
      </div>
      <dl className="mt-2 space-y-1 text-[11px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-mil-dim">{k}</dt>
            <dd className="text-right text-white">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function Side() {
  const c = useController();
  const second = useClockSecond();
  const run = useExercise((s) => s.active);
  const selectedId = useExercise((s) => s.selectedId);
  const events = run.trajectory.events;
  const name = (id: string) => run.scenario.units.find((u) => u.id === id)?.name ?? id;
  const list = useRef<HTMLOListElement>(null);
  // The last event the clock has reached; keep it in view as the run plays.
  const latest = events.reduce((found, e, i) => (e.tS <= second ? i : found), -1);

  useEffect(() => {
    if (latest >= 0) scrollIntoViewSafely(list.current?.querySelector(`[data-event="${latest}"]`));
  }, [latest]);

  return (
    <div className="flex h-full flex-col">
      <SelectedReadout />
      <div className="flex shrink-0 items-baseline justify-between gap-2 px-3 py-2">
        <h2 className="mil-label">Event feed</h2>
        <span className="text-[10px] tabular-nums text-mil-dim">
          {latest + 1} of {events.length}
        </span>
      </div>
      {events.length === 0 ? (
        <p className="px-3 text-[11px] text-mil-dim">
          Nothing is detected, fired or struck in this run, so the feed stays empty. Open Setup to add a sensor, a missile or a mine.
        </p>
      ) : (
        <ol ref={list} aria-label="Events" className="min-h-0 flex-1 overflow-y-auto text-[11px]">
          {events.map((e, i) => {
            const past = i <= latest;
            const focus = eventFocus(e, run.scenario.units);
            const onUnit = focus !== undefined && focus === selectedId;
            return (
              <li key={i} data-event={i} className={cn('border-t border-mil-border/50', onUnit && 'bg-mil-cyan/5')}>
                <div className="flex items-start gap-2 px-3 py-1.5">
                  <span className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: EVENT_COLOR[e.type], opacity: past ? 1 : 0.35 }} />
                  <button
                    className={cn('min-w-0 flex-1 text-left', past ? 'text-mil-text hover:text-white' : 'text-mil-dim hover:text-mil-text')}
                    onClick={() => {
                      c.seek(Math.max(0, e.tS - 8));
                      if (focus) c.select(focus);
                    }}
                  >
                    <span className="mil-value mr-2 tabular-nums">T+{formatClock(e.tS)}</span>
                    <span>{eventText(e, name)}</span>
                  </button>
                  <button
                    title="The collected record this came from"
                    aria-label={`Source data for the event at T+${formatClock(e.tS)}`}
                    className="shrink-0 border border-mil-border px-1 py-0.5 text-[9px] uppercase tracking-wider text-mil-dim hover:border-mil-cyan/60 hover:text-mil-cyan"
                    onClick={() => c.showEventSource(i)}
                  >
                    Source
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
