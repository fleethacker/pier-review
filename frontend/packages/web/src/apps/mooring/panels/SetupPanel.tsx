import { Field, Panel, Select, inputClass } from '../../../shell/ui';
import { cn } from '../../../lib/cn';
import { fmt, lengthFromDisplay, lengthToDisplay, lengthUnit, useUnitSystem } from '../units';
import { useController, useMooring } from './context';
import { WorldPicker } from './WorldPicker';
import { classSupport } from '../classSupport';

export function SetupPanel() {
  useUnitSystem();
  const c = useController();
  const s = useMooring((x) => x);
  const berthLength = s.berth?.face_length_ft ?? 1000;
  const support = classSupport(s.ship, s.shipClassId, s.loading);

  return (
    <Panel title="Scenario" className="space-y-3 p-4">
      <WorldPicker />
      <Field label="Berth">
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
      <div aria-label="Selected class capabilities" className="rounded-sm border border-mil-border bg-mil-bg/60 p-2 text-[11px]">
        <div className="mil-label mb-1">Catalog coverage</div>
        <dl className="space-y-1">
          <div className="flex justify-between gap-2"><dt>Hull reference</dt><dd>{support.current ? 'Available' : 'Loading…'}</dd></div>
          <div className="flex justify-between gap-2"><dt>Environmental load inputs</dt><dd>{support.hasLoadInputs ? 'Present · unqualified' : 'Unavailable'}</dd></div>
          <div className="flex justify-between gap-2"><dt>Mooring fittings</dt><dd>{support.hasFittings ? `${s.ship?.fittings?.length} records` : 'Unavailable'}</dd></div>
          <div className="flex justify-between gap-2"><dt>Planning workflow</dt><dd className="text-mil-amber">{support.canPlan ? 'Demonstration only' : 'Blocked'}</dd></div>
        </dl>
        {support.reason && <p role="status" className="mt-2 text-mil-amber">{support.reason}</p>}
        <p className="mt-2 text-[10px] text-mil-dim">
          Catalog records do not establish class qualification or loading applicability. Seed data remains limited.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Loading">
          <Select
            value={s.loading}
            onChange={(v) => c.setLoading(v)}
            options={(s.ship?.loading_conditions ?? []).map((l) => ({ value: l.name, label: l.name.replace('_', ' ') }))}
          />
        </Field>
        <div role="group" aria-label="Side to pier">
          <span className="mil-label mb-1 block">Side to pier</span>
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
        </div>
      </div>
      <Field label={`Midships position along the pier (${fmt.ft(s.shipXFt)})`}>
        <input
          type="range"
          min={0}
          max={berthLength}
          step={1}
          value={s.shipXFt}
          disabled={!support.current}
          onChange={(e) => c.setShipX(Number(e.target.value))}
          className="w-full accent-cyan-400"
          aria-label="Ship position along the pier"
        />
        <span className="text-[10px] text-mil-dim">Drag a ship with fitting data along or away from the pier; use these controls for exact placement.</span>
      </Field>
      <Field label={`Standoff from face (${lengthUnit()})`}>
        <input
          type="number"
          className={inputClass}
          min={0}
          step={0.5}
          aria-label={`Standoff from face (${lengthUnit()})`}
          disabled={!support.current}
          placeholder="berth default"
          value={s.standoffOverrideFt == null ? '' : Number(lengthToDisplay(s.standoffOverrideFt).toFixed(2))}
          onChange={(e) => c.setStandoff(e.target.value === '' ? null : lengthFromDisplay(Number(e.target.value)))}
        />
      </Field>
    </Panel>
  );
}
