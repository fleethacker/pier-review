import { Field, Panel, Select, inputClass } from '../../../shell/ui';
import { cn } from '../../../lib/cn';
import { fmt } from '../units';
import { useController, useMooring } from './context';

export function SetupPanel() {
  const c = useController();
  const s = useMooring((x) => x);
  const berthLength = s.berth?.face_length_ft ?? 1000;
  const noFittings = s.ship && (s.ship.fittings?.length ?? 0) === 0;

  return (
    <Panel title="Scenario" className="space-y-3 p-4">
      <Field label="Pier / berth">
        <Select
          value={s.berthId}
          onChange={(v) => void c.setBerth(v)}
          options={s.berths.map((b) => ({ value: b.berth_id, label: b.name }))}
        />
      </Field>
      <Field label="Ship class">
        <Select
          value={s.shipClassId}
          onChange={(v) => void c.setShip(v)}
          options={s.ships.map((x) => ({
            value: x.class_id,
            label: `${x.class_id} · ${x.name}${x.has_fittings ? '' : ' (hull only)'}`,
          }))}
        />
      </Field>
      {noFittings && (
        <p className="text-[11px] text-mil-amber">
          This class has no fitting data yet, so lines cannot be placed. The hull is shown for reference.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Loading">
          <Select
            value={s.loading}
            onChange={(v) => c.setLoading(v)}
            options={(s.ship?.loading_conditions ?? []).map((l) => ({ value: l.name, label: l.name.replace('_', ' ') }))}
          />
        </Field>
        <Field label="Side to pier">
          <div className="flex">
            {(['port', 'starboard'] as const).map((side) => (
              <button
                key={side}
                onClick={() => void c.setSide(side)}
                aria-pressed={s.side === side}
                className={cn(
                  'h-8 flex-1 border font-mono text-[11px] uppercase',
                  s.side === side
                    ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan'
                    : 'border-mil-border bg-mil-bg text-mil-text hover:text-white',
                )}
              >
                {side}
              </button>
            ))}
          </div>
        </Field>
      </div>
      <Field label={`Midships position along the pier (${fmt.ft(s.shipXFt)})`}>
        <input
          type="range"
          min={0}
          max={berthLength}
          step={1}
          value={s.shipXFt}
          disabled={!!noFittings}
          onChange={(e) => c.setShipX(Number(e.target.value))}
          className="w-full accent-cyan-400"
          aria-label="Ship position along the pier"
        />
        <span className="text-[10px] text-mil-dim">Or drag the ship on the canvas.</span>
      </Field>
      <Field label="Standoff from face (ft)">
        <input
          type="number"
          className={inputClass}
          min={0}
          step={0.5}
          placeholder="berth default"
          value={s.standoffOverrideFt ?? ''}
          onChange={(e) => c.setStandoff(e.target.value === '' ? null : Number(e.target.value))}
        />
      </Field>
    </Panel>
  );
}
