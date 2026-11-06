import { cn } from './lib/cn';
import { useClockSecond, useController, useExercise } from './context';
import { bearingTo, distanceM, formatLatLon, mToNm } from './geo';
import { SHIP_CLASSES, SIDE_COLORS } from './ships';
import { unitHp, statesAt } from './sim';
import { STATUS_COLOR, STATUS_LABEL, unitStatus } from './status';

const bearing = (deg: number) => `${Math.round(deg).toString().padStart(3, '0')}°`;

const HEAD = 'px-3 py-1.5 text-left text-[9px] font-medium uppercase tracking-widest text-mil-dim';

/** Every unit in the run with its state at the moment on the clock: the tabular view of what the map draws. */
export function Contacts() {
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
