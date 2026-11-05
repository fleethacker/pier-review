import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '../../../lib/cn';
import { Button, BackendBadge, Field, Panel, Select, StatusChip, inputClass, toStatus } from '../../../shell/ui';
import { STATUS_COLOR } from '../../../shell/theme';
import { useController, useMooring } from '../panels/context';
import { analyzeBerthImage, confirmBerth } from './client';
import { IMAGE_KINDS, applyEdits, canConfirm, checkImage, confidenceBand, estimatedCapacityNote, pendingConfirmations } from './logic';
import type { ImageKind, VisionResponse } from './logic';

type Phase = 'idle' | 'analyzing' | 'review' | 'saving' | 'done' | 'error';

const BAND_COLOR = { high: STATUS_COLOR.GREEN, medium: STATUS_COLOR.AMBER, low: STATUS_COLOR.RED } as const;

/** Upload an image of a berth, review what was detected, confirm the uncertain parts, and use the saved berth. */
export function BerthVisionPanel() {
  const c = useController();
  const shipClassId = useMooring((s) => s.shipClassId);
  const side = useMooring((s) => s.side);
  const [phase, setPhase] = useState<Phase>('idle');
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [kind, setKind] = useState<ImageKind>('satellite');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<{ jobId: string; response: VisionResponse } | null>(null);
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const [name, setName] = useState('');
  const [bearing, setBearing] = useState(0);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!file) return setPreviewUrl(null);
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const result = job?.response.result;
  const pending = useMemo(() => pendingConfirmations(result?.detections ?? []), [result]);
  const capacityNote = estimatedCapacityNote(result?.questions ?? []);

  const reset = () => {
    abort.current?.abort();
    setPhase('idle');
    setJob(null);
    setConfirmed(new Set());
    setError(null);
    setProgress(0);
  };

  const analyze = async () => {
    if (!file) return;
    const problem = checkImage(file);
    if (problem) {
      setError(problem);
      setPhase('error');
      return;
    }
    abort.current?.abort();
    abort.current = new AbortController();
    setPhase('analyzing');
    setError(null);
    setProgress(0);
    try {
      const out = await analyzeBerthImage({ image: file, kind, berthName: name.trim() || undefined, shipClassId: shipClassId || undefined, side }, setProgress, abort.current.signal);
      setJob(out);
      setName(out.response.result.draft_berth.name);
      setBearing(out.response.result.draft_berth.face_bearing_true_deg);
      setConfirmed(new Set());
      setPhase('review');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      setError(e instanceof Error ? e.message : String(e));
      setPhase('error');
    }
  };

  const save = async () => {
    if (!job || !result) return;
    setPhase('saving');
    setError(null);
    try {
      const berthId = await confirmBerth(job.jobId, applyEdits(result.draft_berth, { name, faceBearingDeg: bearing }));
      await c.adoptBerth(berthId);
      setPhase('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase('review');
    }
  };

  const toggle = (id: string) =>
    setConfirmed((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <Panel title="Berth from an image" className="space-y-2 p-4">
      {(phase === 'idle' || phase === 'error' || phase === 'analyzing') && (
        <div className="space-y-2">
          <Field label="Image of the berth">
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              aria-label="Berth image"
              className="block w-full text-[11px] text-mil-dim file:mr-2 file:rounded-sm file:border file:border-mil-border file:bg-mil-panel file:px-2 file:py-1 file:text-mil-text"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setError(null);
                if (phase === 'error') setPhase('idle');
              }}
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Image type">
              <Select value={kind} onChange={(v) => setKind(v as ImageKind)} options={IMAGE_KINDS} />
            </Field>
            <Field label="Berth name (optional)">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>
          <Button size="sm" disabled={!file || phase === 'analyzing'} onClick={() => void analyze()}>
            {phase === 'analyzing' ? `Analyzing… ${Math.round(progress * 100)}%` : 'Analyze image'}
          </Button>
          {phase === 'analyzing' && (
            <Button size="sm" variant="ghost" className="ml-2" onClick={reset}>
              Cancel
            </Button>
          )}
          <p className="text-[10px] text-mil-dim">The result is a draft. Nothing is used until you confirm it.</p>
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-sm border border-mil-red/40 bg-mil-red/10 p-2 text-[11px] text-mil-red">
          {error}
        </div>
      )}

      {(phase === 'review' || phase === 'saving') && job && result && (
        <div className="space-y-3 text-[11px]">
          <div className="flex flex-wrap items-center gap-2">
            <BackendBadge backend={job.response.backend} />
            <StatusChip status={toStatus(job.response.status)} label={`status ${job.response.status}`} />
            <span className="font-mono text-[10px] uppercase tracking-wider text-mil-amber">draft: needs your confirmation</span>
          </div>

          {result.draft_berth.provenance?.notes && (
            <p className="rounded-sm border border-mil-amber/40 bg-mil-amber/10 p-2 text-[10px] text-mil-amber">{result.draft_berth.provenance.notes}</p>
          )}
          {(job.response.assumptions ?? []).map((a, i) => (
            <p key={`${i}-${a}`} className="text-[10px] text-mil-dim">{a}</p>
          ))}

          {previewUrl && (
            <div className="relative overflow-hidden rounded-sm border border-mil-border">
              <img src={previewUrl} alt="Uploaded berth" className="block w-full" onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
              {natural && (
                <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${natural.w} ${natural.h}`} preserveAspectRatio="none" role="img" aria-label="Detections on the image">
                  {result.detections.map((d) => {
                    const [x, y, w, h] = d.bbox_px;
                    const color = d.needs_confirmation ? STATUS_COLOR.AMBER : BAND_COLOR[confidenceBand(d.confidence)];
                    return <rect key={d.item_id} x={x} y={y} width={w} height={h} fill="none" stroke={color} strokeWidth={Math.max(natural.w, natural.h) / (d.needs_confirmation ? 160 : 400)} />;
                  })}
                </svg>
              )}
            </div>
          )}
          <p className="text-[10px] text-mil-dim">
            {result.detections.length} detections. Amber boxes need confirmation; others are green (80% or more), amber or red by confidence.
          </p>

          <div className="grid grid-cols-2 gap-2">
            <Field label="Berth name">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Face bearing (°T)">
              <input type="number" className={inputClass} step={0.5} value={bearing} onChange={(e) => setBearing(Number(e.target.value))} />
            </Field>
          </div>
          <p className="text-[10px] text-mil-dim">
            {result.draft_berth.fittings.length} fittings, {result.draft_berth.fenders?.length ?? 0} fenders, {result.draft_berth.face_length_ft.toFixed(0)} ft of face, deck {result.draft_berth.deck_height_mllw_ft.toFixed(1)} ft above MLLW.
          </p>
          {capacityNote && <p className="rounded-sm border border-mil-amber/40 p-2 text-[10px] text-mil-amber">Estimated: {capacityNote}</p>}

          <div>
            <div className="mil-label mb-1">
              Confirm these ({pending.filter((d) => confirmed.has(d.item_id)).length} of {pending.length})
            </div>
            {pending.length === 0 ? (
              <p className="text-mil-dim">Nothing was flagged. Still check the draft against the image.</p>
            ) : (
              <ul className="space-y-1">
                {pending.map((d) => (
                  <li key={d.item_id}>
                    <label className="flex cursor-pointer items-center gap-2">
                      <input type="checkbox" checked={confirmed.has(d.item_id)} onChange={() => toggle(d.item_id)} />
                      <span className={cn(confirmed.has(d.item_id) ? 'text-white' : 'text-mil-amber')}>
                        {d.item_id} · {d.kind.replace(/_/g, ' ')} · {Math.round(d.confidence * 100)}% sure
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {result.questions.filter((q) => q !== capacityNote && !pending.some((d) => q.includes(d.item_id))).map((q, i) => (
            <p key={`${i}-${q}`} className="text-[10px] text-mil-dim">? {q}</p>
          ))}

          <div className="flex gap-2">
            <Button size="sm" disabled={!canConfirm(result.detections, confirmed, name) || phase === 'saving'} onClick={() => void save()}>
              {phase === 'saving' ? 'Saving…' : 'Confirm and use this berth'}
            </Button>
            <Button size="sm" variant="secondary" onClick={reset} disabled={phase === 'saving'}>
              Discard
            </Button>
          </div>
          {!canConfirm(result.detections, confirmed, name) && (
            <p className="text-[10px] text-mil-dim">Tick every amber item and give the berth a name to continue.</p>
          )}
        </div>
      )}

      {phase === 'done' && (
        <div role="status" className="space-y-2 text-[11px]">
          <p className="text-mil-green">Saved “{name}” and selected it. Its data source is “vision”: check every fitting against the real pier before relying on it.</p>
          <Button size="sm" variant="secondary" onClick={() => { setFile(null); reset(); }}>
            Analyze another image
          </Button>
        </div>
      )}
    </Panel>
  );
}
