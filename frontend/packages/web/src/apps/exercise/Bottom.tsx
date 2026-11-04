import { cn } from '../../lib/cn';
import { Button } from '../../shell/ui';
import { useClockSecond, useController, useExercise } from './context';
import { PLAYBACK_RATES } from './controller';
import { bearingTo, distanceM, formatClock, formatLatLon, mToNm } from './geo';
import { SHIP_CLASSES, SIDE_COLORS } from './ships';
import { statesAt } from './sim';

const bearing = (deg: number) => `${Math.round(deg).toString().padStart(3, '0')}°`;

function PlaybackBar() {
  const c = useController();
  const second = useClockSecond();
  const playing = useExercise((s) => s.playing);
  const rate = useExercise((s) => s.rate);
  const duration = useExercise((s) => s.active.scenario.durationS);
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
      <input
        type="range"
        aria-label="Time"
        className="min-w-0 flex-1"
        min={0}
        max={duration}
        step={1}
        value={second}
        onChange={(e) => c.seek(Number(e.target.value))}
      />
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

function Contacts() {
  const c = useController();
  const second = useClockSecond();
  const run = useExercise((s) => s.active);
  const selectedId = useExercise((s) => s.selectedId);
  const states = statesAt(run.trajectory, second);
  const ref = states[run.trajectory.unitIds.indexOf(selectedId ?? '')];
  const head = 'px-3 py-1.5 text-left text-[9px] font-medium uppercase tracking-widest text-mil-dim';
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 bg-mil-panel">
          <tr>
            <th className={head}>Ship</th>
            <th className={head}>Class</th>
            <th className={head}>Hdg</th>
            <th className={head}>STW kt</th>
            <th className={head}>SOG kt</th>
            <th className={head}>Position</th>
            <th className={head}>{ref ? 'Rng nm / Brg from selected' : 'Rng / Brg'}</th>
          </tr>
        </thead>
        <tbody>
          {run.scenario.units.map((u, i) => {
            const st = states[i];
            const selected = u.id === selectedId;
            return (
              <tr
                key={u.id}
                onClick={() => c.select(selected ? null : u.id)}
                className={cn('cursor-pointer border-t border-mil-border/50', selected ? 'bg-mil-cyan/10 text-white' : 'text-mil-text hover:text-white')}
              >
                <td className="px-3 py-1">
                  <span className="mr-2 inline-block h-2 w-2 rounded-full align-middle" style={{ background: SIDE_COLORS[u.side] }} />
                  {u.name}
                </td>
                <td className="px-3 py-1">{SHIP_CLASSES[u.classId].id}</td>
                <td className="px-3 py-1 tabular-nums">{bearing(st.headingDeg)}</td>
                <td className="px-3 py-1 tabular-nums">{st.speedKt.toFixed(1)}</td>
                <td className="px-3 py-1 tabular-nums">{st.sogKt.toFixed(1)}</td>
                <td className="px-3 py-1 tabular-nums">{formatLatLon(st)}</td>
                <td className="px-3 py-1 tabular-nums">
                  {ref && !selected ? `${mToNm(distanceM(ref, st)).toFixed(2)} / ${bearing(bearingTo(ref, st))}` : '–'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Bottom() {
  return (
    <div className="flex h-full flex-col">
      <PlaybackBar />
      <Contacts />
    </div>
  );
}
