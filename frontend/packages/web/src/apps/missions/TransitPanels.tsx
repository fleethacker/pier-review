import { cn } from '../../lib/cn';
import { Button, Field, Select, inputClass } from '../../shell/ui';
import { useController, useMissions } from './context';
import { fmtSimTime, num } from './fmt';
import { ErrorLine, FollowToggle, Heading, Notice, ValidityBadge, ValidityReasons, chipBtn } from './parts';
import { SPEEDS, endTime } from './playback';
import { VESSEL_COLORS } from './scene';
import type { TransitEvent, VesselTransit } from './types';

export const TRANSIT_DISCLAIMER = 'Surrogate maneuvering model; propulsion assumed; not navigational advice.';

/** Always-visible limits of the transit model: the disclaimer, the envelope's validity reasons and assumptions. */
export function TransitNotice() {
  const res = useMissions((s) => s.response);
  const sample = useMissions((s) => s.sampleTransit);
  return (
    <section aria-label="Model limits" className="rounded-sm border border-mil-amber/60 bg-mil-amber/10 p-2 text-[11px] text-mil-amber">
      <p className="font-medium uppercase tracking-wider">{TRANSIT_DISCLAIMER}</p>
      {sample && <p className="mt-1">MOCK sample run: a fixture, not a simulation.</p>}
      {res ? (
        <>
          <p className="mt-1">
            Validity <ValidityBadge validity={res.validity} /> (status {res.status}, backend {res.backend})
          </p>
          <ValidityReasons validity={res.validity} />
          {(res.assumptions ?? []).length > 0 && (
            <>
              <p className="mt-1 uppercase tracking-wider">Assumptions</p>
              <ul className="list-disc pl-4 text-mil-text">
                {(res.assumptions ?? []).map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <p className="mt-1 text-mil-text">Run a simulation to see its validity reasons and assumptions.</p>
      )}
    </section>
  );
}

function VesselForm({ idx, v }: { idx: number; v: VesselTransit }) {
  const c = useController();
  return (
    <fieldset className="space-y-2 rounded-sm border border-mil-border p-2">
      <legend className="px-1 text-[11px] text-white">
        {v.vessel_id} <span className="text-mil-dim">({v.ship_class_id})</span>
      </legend>
      <Field label="Mode">
        <Select
          value={v.mode ?? 'own_thrust'}
          onChange={(m) => c.editVessel(idx, { mode: m as VesselTransit['mode'] })}
          options={[{ value: 'own_thrust', label: 'Own thrust' }, { value: 'tug_assisted', label: 'Tug assisted' }]}
        />
      </Field>
      <Field label="Max speed, calm water (kt; blank = class default)">
        <input
          className={inputClass}
          inputMode="decimal"
          defaultValue={v.propulsion?.max_speed_kt ?? ''}
          key={`${v.vessel_id}-${v.propulsion?.max_speed_kt ?? 'x'}`}
          onBlur={(e) => {
            const t = e.target.value.trim();
            const n = Number(t);
            c.editVessel(idx, { maxSpeedKt: t === '' ? null : Number.isFinite(n) && n > 0 && n <= 40 ? n : (v.propulsion?.max_speed_kt ?? null) });
          }}
        />
      </Field>
      <div>
        <span className="mil-label mb-1 block">Route speeds (kt)</span>
        <div className="grid grid-cols-2 gap-2">
          {v.route.map((w, j) => (
            <label key={j} className="block text-[10px] text-mil-dim">
              {w.name ?? `WP${j + 1}`}
              <input
                className={inputClass}
                inputMode="decimal"
                defaultValue={w.speed_kt}
                key={`${v.vessel_id}-${j}-${w.speed_kt}`}
                onBlur={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n >= 0 && n <= 35) c.editVessel(idx, { routeSpeed: { wp: j, kt: n } });
                }}
              />
            </label>
          ))}
        </div>
      </div>
    </fieldset>
  );
}

export function TransitSidebar() {
  const c = useController();
  const presets = useMissions((s) => s.presets);
  const presetId = useMissions((s) => s.presetId);
  const request = useMissions((s) => s.request);
  const text = useMissions((s) => s.requestText);
  const reqErr = useMissions((s) => s.requestError);
  const running = useMissions((s) => s.running);
  const progress = useMissions((s) => s.progress);
  const err = useMissions((s) => s.transitError);
  const note = useMissions((s) => s.transitNotice);
  const response = useMissions((s) => s.response);
  const busy = useMissions((s) => s.busy);
  return (
    <div className="space-y-3">
      <TransitNotice />
      <Field label="Preset">
        <Select value={presetId ?? ''} onChange={(id) => c.selectPreset(id)} options={presets.map((p) => ({ value: p.preset_id, label: p.title }))} />
      </Field>
      {presets.find((p) => p.preset_id === presetId)?.description && <p className="text-[11px] text-mil-dim">{presets.find((p) => p.preset_id === presetId)?.description}</p>}
      {request?.vessels.map((v, i) => <VesselForm key={v.vessel_id} idx={i} v={v} />)}
      <details>
        <summary className="mil-label cursor-pointer">Request JSON</summary>
        <textarea aria-label="Transit request JSON" className={cn(inputClass, 'mt-1 h-48 font-mono')} spellCheck={false} value={text} onChange={(e) => c.setRequestText(e.target.value)} />
        {reqErr && <p className="text-[11px] text-mil-red">{reqErr}</p>}
      </details>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void c.run()} disabled={!request || !!reqErr || running}>
          {running ? 'Running...' : 'Run'}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void c.saveAsMission()} disabled={!response || !!busy} title="Create a mission per vessel from the simulated track">
          Save as mission
        </Button>
      </div>
      {running && <progress aria-label="Simulation progress" className="w-full" max={1} value={progress} />}
      <ErrorLine text={err} />
      <Notice text={note} />
    </div>
  );
}

export function TransitSide() {
  return (
    <section aria-label="Map key" className="space-y-1 text-[11px] text-mil-text">
      <Heading>Key</Heading>
      <p>Hull outline follows the ship heading; scaled to ship length when the ship class is known, otherwise a fixed glyph labeled "not to scale".</p>
      <p>Thin trail: recent path (last 300 points). Orange arrow: tug force at its hull contact point, length proportional to force.</p>
      <p>Tug hull positions are not modeled; the arrow shows force only.</p>
      <FollowToggle label="Keep the vessels centered (the map shows about 8 km at a time)" />
    </section>
  );
}

const KIND_TEXT: Record<TransitEvent['kind'], string> = {
  waypoint_reached: 'waypoint reached',
  arrived: 'arrived',
  rudder_saturated: 'rudder saturated',
  tug_saturated: 'tug saturated',
  large_cross_track: 'large cross-track',
  stopped_short: 'stopped short',
  integration_failed: 'integration failed',
};

export function PlaybackControls() {
  const c = useController();
  const clock = useMissions((s) => s.clock);
  const series = useMissions((s) => s.series);
  if (!series) return <p className="p-3 text-[11px] text-mil-dim">Run a simulation to play it back.</p>;
  const end = endTime(series.frames);
  return (
    <div className="flex flex-wrap items-center gap-3 px-3 py-2">
      <Button size="sm" onClick={() => (clock.playing ? c.pause() : c.play())} aria-label={clock.playing ? 'Pause' : 'Play'}>
        {clock.playing ? 'Pause' : 'Play'}
      </Button>
      <input
        type="range"
        aria-label="Simulation time"
        aria-valuetext={`${fmtSimTime(clock.t)} of ${fmtSimTime(end)}`}
        className="min-w-[8rem] flex-1 accent-cyan-400"
        min={0}
        max={end}
        step={Math.max(0.5, end / 1000)}
        value={clock.t}
        onChange={(e) => c.setPlayhead(Number(e.target.value))}
      />
      <span className="w-24 text-[11px] text-white">
        {fmtSimTime(clock.t)} / {fmtSimTime(end)}
      </span>
      <div role="group" aria-label="Playback speed" className="flex">
        {SPEEDS.map((s) => (
          <button key={s} aria-pressed={clock.speed === s} className={chipBtn(clock.speed === s)} onClick={() => c.setSpeed(s)}>
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}

export function VesselTable() {
  const c = useController();
  const vessels = useMissions((s) => s.vessels);
  const selected = useMissions((s) => s.selectedVesselId);
  if (!vessels.length) return null;
  const head = ['Vessel', 'SOG kt', 'STW kt', 'HDG T', 'Rudder', 'Engine', 'Thrust lbf', 'XTE ft', 'To go nm', 'Status'];
  return (
    <table aria-label="Vessels" className="w-full text-left text-[11px]">
      <thead className="text-mil-dim">
        <tr>
          {head.map((h) => (
            <th key={h} scope="col" className="px-2 py-1 font-normal">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {vessels.map((v, i) => (
          <tr key={v.vessel_id} aria-selected={v.vessel_id === selected} className={cn('cursor-pointer', v.vessel_id === selected && 'bg-mil-cyan/10')} onClick={() => c.selectVessel(v.vessel_id)}>
            <th scope="row" className="px-2 py-0.5 font-normal text-white">
              <span aria-hidden style={{ color: VESSEL_COLORS[i % VESSEL_COLORS.length] }}>
                {'■'}{' '}
              </span>
              {v.vessel_id}
            </th>
            <td className="px-2">{num(v.sog_kt)}</td>
            <td className="px-2">{num(v.stw_kt)}</td>
            <td className="px-2">{num(v.heading_true_deg, 0)}</td>
            <td className="px-2">{num(v.rudder_deg, 0)}</td>
            <td className="px-2">{num(v.engine_order, 2)}</td>
            <td className="px-2">{num(v.thrust_lbf, 0)}</td>
            <td className="px-2">{num(v.cross_track_ft, 0)}</td>
            <td className="px-2">{num(v.distance_to_go_nm, 2)}</td>
            <td className={cn('px-2', v.status !== 'underway' && v.status !== 'arrived' && 'text-mil-amber')}>
              {v.status}
              {(v.tugs ?? []).length > 0 && ` (${v.tugs?.length} tug${v.tugs?.length === 1 ? '' : 's'})`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TransitEvents() {
  const c = useController();
  const res = useMissions((s) => s.response);
  const clock = useMissions((s) => s.clock);
  if (!res) return null;
  return (
    <ul aria-label="Transit events" className="text-[11px]">
      {res.result.events.map((e, i) => (
        <li key={i}>
          <button onClick={() => c.seekEvent(e.t_s)} aria-current={e.t_s <= clock.t ? 'true' : undefined} className={cn('flex w-full gap-2 px-2 py-0.5 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-mil-cyan/60', e.t_s <= clock.t ? 'text-white' : 'text-mil-dim', e.kind.endsWith('saturated') && 'text-mil-amber')}>
            <span className="w-12 shrink-0">{fmtSimTime(e.t_s)}</span>
            <span className="w-28 shrink-0">{e.vessel_id}</span>
            <span className="w-32 shrink-0">{KIND_TEXT[e.kind]}</span>
            <span className="min-w-0 truncate">{e.detail}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function TransitBottom() {
  return (
    <div className="flex h-full flex-col">
      <PlaybackControls />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto border-t border-mil-border md:grid-cols-2">
        <div className="overflow-x-auto">
          <VesselTable />
        </div>
        <div className="border-mil-border md:border-l">
          <TransitEvents />
        </div>
      </div>
    </div>
  );
}
