import { useEffect, useState } from 'react';
import { cn } from '../../lib/cn';
import { Field, Select } from '../../shell/ui';
import { WHAT_IFS, bannerText, limitedText, missingHazards, selectedAltId } from './camera';
import { useController, useMissions } from './context';
import { ErrorLine, FollowToggle, Heading, ValidityBadge, ValidityReasons, chipBtn } from './parts';

export function CameraToggle() {
  const c = useController();
  const on = useMissions((s) => s.cameraOn);
  return (
    <label className="mt-2 flex items-center gap-2 text-[11px] text-mil-text">
      <input type="checkbox" checked={on} onChange={(e) => c.setCameraOn(e.target.checked)} />
      Backup camera (predict the selected vessel from the playhead)
    </label>
  );
}

function useAgeS(atMs: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return atMs == null ? null : Math.max(0, Math.round((now - atMs) / 1000));
}

/** Validity, banner, hazards and age: the always-visible part of the camera. */
export function CameraStatus() {
  const res = useMissions((s) => s.camResult);
  const sample = useMissions((s) => s.camSample);
  const err = useMissions((s) => s.camError);
  const whatIf = useMissions((s) => s.camWhatIf);
  const at = useMissions((s) => s.camAtMs);
  const playbackLag = useMissions((s) => s.camSource === 'transit' && s.camInputTimeS != null ? Math.max(0, s.clock.t - s.camInputTimeS) : 0);
  const age = useAgeS(at);
  if (!res)
    return (
      <>
        <ErrorLine text={err} />
        <p className="text-[11px] text-mil-dim">
          Waiting for a prediction. For Transit, run a simulation first.
        </p>
      </>
    );
  const selId = selectedAltId(res, whatIf);
  const hold = res.result.alternatives.find((a) => a.alt_id === 'hold');
  const sel = res.result.alternatives.find((a) => a.alt_id === selId);
  const missing = missingHazards(res);
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-mil-text">Prediction for {res.result.vessel_id} at {res.result.as_of_utc}</p>
      {playbackLag > 1 && <p role="status" className="text-[11px] text-mil-amber">Prediction is {Math.round(playbackLag)} simulated seconds behind playback; refresh pending.</p>}
      {sample && (
        <p
          role="status"
          className="rounded-sm border border-mil-red/60 bg-mil-red/10 px-2 py-1 font-mono text-[10px] uppercase text-mil-red"
        >
          Sample prediction (backend unavailable)
        </p>
      )}
      <section
        aria-label="Prediction limits"
        className="rounded-sm border border-mil-amber/60 bg-mil-amber/10 p-2 text-[11px] text-mil-amber"
      >
        <p className="font-medium">
          <ValidityBadge validity={res.validity} /> {limitedText(res)}
        </p>
        <ValidityReasons validity={res.validity} />
      </section>
      {[hold, sel].map((a) => {
        if (!a) return null;
        const b = bannerText(a);
        return (
          <p
            key={a.alt_id}
            role={b.level === 'breach' ? 'alert' : 'status'}
            className={cn(
              'rounded-sm border px-2 py-1 text-[11px]',
              b.level === 'breach'
                ? 'border-mil-red bg-mil-red/20 font-semibold text-mil-red'
                : 'border-mil-border text-mil-text',
            )}
          >
            <span className="text-mil-dim">{a.alt_id === 'hold' ? 'Hold: ' : `${a.label}: `}</span>
            {b.text}
            {!a.corridor && <span className="block text-mil-amber">Uncertainty unavailable: no corridor supplied.</span>}
          </p>
        );
      })}
      {missing.length > 0 && (
        <p className="text-[11px] text-mil-amber">Hazards not checked: {missing.join(', ')}</p>
      )}
      <p className="text-[10px] text-mil-dim">
        Last prediction {age ?? 0} s ago; input age {Math.round(res.result.input_age_s)} s.
      </p>
      <ErrorLine text={err} />
    </div>
  );
}

export function CameraSidebar() {
  const c = useController();
  const src = useMissions((s) => s.camSource);
  const presets = useMissions((s) => s.camPresets);
  const presetId = useMissions((s) => s.camPresetId);
  const whatIf = useMissions((s) => s.camWhatIf);
  const hasSeries = useMissions((s) => !!s.series);
  return (
    <div className="space-y-3">
      <Heading>Backup camera</Heading>
      <div role="group" aria-label="Starting state" className="flex">
        <button
          aria-pressed={src === 'transit'}
          className={chipBtn(src === 'transit')}
          onClick={() => c.setCamSource('transit')}
        >
          Transit vessel
        </button>
        <button
          aria-pressed={src === 'preset'}
          className={chipBtn(src === 'preset')}
          onClick={() => c.setCamSource('preset')}
        >
          Preset
        </button>
      </div>
      {src === 'transit' ? (
        <>
          <p className="text-[11px] text-mil-dim">
            {hasSeries
              ? 'Predicting the selected vessel at the Transit playback time. Press Play on the Transit tab and switch back, or use the Transit tab toggle.'
              : 'Run a simulation on the Transit tab first.'}
          </p>
          <FollowToggle label="Keep the vessel centered" />
        </>
      ) : (
        <Field label="Preset">
          <Select
            value={presetId ?? ''}
            onChange={(id) => c.setCamPreset(id)}
            options={presets.map((p) => ({ value: p.preset_id, label: p.title }))}
          />
        </Field>
      )}
      <div role="group" aria-label="What if" className="flex flex-wrap gap-1">
        <button
          aria-pressed={whatIf === null}
          className={chipBtn(whatIf === null)}
          onClick={() => c.setWhatIf(null)}
        >
          Hold only
        </button>
        {WHAT_IFS.map((w) => (
          <button
            key={w.id}
            aria-pressed={whatIf === w.id}
            className={chipBtn(whatIf === w.id)}
            onClick={() => c.setWhatIf(w.id)}
          >
            {w.label}
          </button>
        ))}
      </div>
      <CameraStatus />
    </div>
  );
}

export function CameraSide() {
  return (
    <section aria-label="Camera key" className="space-y-1 text-[11px] text-mil-text">
      <Heading>Key</Heading>
      <p>
        <span className="text-cyan-400">Cyan</span>: hold current commands.{' '}
        <span className="text-orange-400">Orange</span>: selected what-if. Grey: other alternatives.
      </p>
      <p>
        Hull outlines every 30 s (+30s, +60s...). When supplied, the translucent area shows the reported uncertainty corridor. Yellow dot: closest approach. Red marker: predicted contact.
      </p>
      <p>Samples are a seeded spread, not a calibrated probability.</p>
    </section>
  );
}

export function CameraBanner() {
  const res = useMissions((s) => s.camResult);
  const sample = useMissions((s) => s.camSample);
  const error = useMissions((s) => s.camError);
  const playbackLag = useMissions((s) => s.camSource === 'transit' && s.camInputTimeS != null ? Math.max(0, s.clock.t - s.camInputTimeS) : 0);
  if (!res) return <span role="status" className="text-[10px] text-mil-amber">{error ?? 'Waiting for a prediction for the selected vessel.'}</span>;
  const hold = res.result.alternatives.find((a) => a.alt_id === 'hold');
  const b = bannerText(hold);
  return (
    <span
      role="status"
      className={cn(
        'rounded-sm border px-2 py-0.5 font-mono text-[10px]',
        b.level === 'breach'
          ? 'border-mil-red bg-mil-red/20 text-mil-red'
          : 'border-mil-border text-mil-text',
      )}
    >
      {sample ? 'Sample prediction: ' : ''}
      Prediction for {res.result.vessel_id} at {res.result.as_of_utc} · {b.text}
      {playbackLag > 1 ? ` · Prediction is ${Math.round(playbackLag)} simulated seconds behind playback; refresh pending.` : ''}
      {res.validity?.reasons?.some((r) => r.code.startsWith('HAZARD_COVERAGE_')) ? ' · Hazard coverage incomplete or unknown; no all-clear.' : ''}
      {hold && !hold.corridor ? ' · Uncertainty unavailable.' : ''}
    </span>
  );
}
