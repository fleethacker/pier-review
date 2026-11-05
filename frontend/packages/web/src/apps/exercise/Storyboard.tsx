import { useEffect, useRef, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, Field, Panel, Select, inputClass } from '../../shell/ui';
import { useClockSecond, useController, useExercise } from './context';
import { downloadText, fileSafe, openReport, storyboardHtml } from './exportResults';
import { formatClock } from './geo';
import { NumField } from './NumField';
import { imageBytes, MIN_HOLD_S, readImageFile, scrollIntoViewSafely } from './storyboard';
import { STOCK, stockByUrl } from './stockImages';
import type { StoryMoment } from './types';

const kb = (bytes: number) => (bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.round(bytes / 1000)} kB`);

/** Pictures a moment can have: one of ours, one off the map, or one from a file. */
function PicturePicker({ moment }: { moment: StoryMoment }) {
  const c = useController();
  const canCapture = useExercise((s) => s.canCapture);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const credit = stockByUrl(moment.image);

  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(what);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!canCapture || busy !== null}
          title={canCapture ? 'Take a picture of the map as it looks now' : 'The map is not loaded yet'}
          onClick={() =>
            void run('capture', async () => {
              if (!(await c.captureInto(moment.id))) throw new Error('The map could not be captured. Give it a moment to load and try again.');
            })
          }
        >
          {busy === 'capture' ? 'Capturing…' : 'Capture the map'}
        </Button>
        <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => file.current?.click()}>
          Load a picture
        </Button>
        {moment.image && (
          <Button size="sm" variant="ghost" onClick={() => c.patchMoment(moment.id, { image: undefined })}>
            Remove the picture
          </Button>
        )}
        <input
          ref={file}
          type="file"
          accept="image/*"
          aria-label={`Picture file for ${moment.title}`}
          className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            e.target.value = '';
            if (chosen) void run('file', async () => c.patchMoment(moment.id, { image: await readImageFile(chosen) }));
          }}
        />
      </div>
      <details>
        <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-mil-dim hover:text-mil-text">Or pick a stock picture</summary>
        <div className="mt-2 grid grid-cols-5 gap-1.5">
          {STOCK.map((s) => (
            <button
              key={s.id}
              title={`${s.label} — ${s.source.title}`}
              aria-label={`Use the picture: ${s.label}`}
              aria-pressed={moment.image === s.url}
              onClick={() => c.patchMoment(moment.id, { image: s.url })}
              className={cn('overflow-hidden border', moment.image === s.url ? 'border-mil-cyan' : 'border-mil-border hover:border-mil-text')}
            >
              <img src={s.url} alt="" className="h-9 w-full object-cover" />
            </button>
          ))}
        </div>
      </details>
      {credit && (
        <p className="text-[9px] leading-snug text-mil-dim">
          {credit.label} — {credit.source.title}. {credit.source.license}, from Wikimedia Commons.
        </p>
      )}
      {error && (
        <p role="alert" className="text-[10px] text-mil-red">
          {error}
        </p>
      )}
    </div>
  );
}

function MomentCard({ moment, index }: { moment: StoryMoment; index: number }) {
  const c = useController();
  const units = useExercise((s) => s.scenario.units);
  const focused = useExercise((s) => s.focusedMomentId === moment.id);
  const duration = useExercise((s) => s.scenario.durationS);
  const box = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(focused);

  useEffect(() => {
    if (!focused) return;
    setOpen(true);
    scrollIntoViewSafely(box.current);
  }, [focused]);

  return (
    <details
      ref={box}
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      className={cn('border', focused ? 'border-mil-cyan/60' : 'border-mil-border')}
    >
      <summary className="flex cursor-pointer items-center gap-2 p-1.5">
        {moment.image ? (
          <img src={moment.image} alt="" className="h-9 w-14 shrink-0 border border-mil-border object-cover" />
        ) : (
          <span className="flex h-9 w-14 shrink-0 items-center justify-center border border-dashed border-mil-border text-[9px] text-mil-dim">no picture</span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[11px] text-white">
            {index + 1}. {moment.title}
          </span>
          <span className="block text-[10px] tabular-nums text-mil-dim">
            T+{formatClock(moment.atS)} for {moment.holdS}s{moment.unitId ? ` · ${units.find((u) => u.id === moment.unitId)?.name ?? moment.unitId}` : ''}
          </span>
        </span>
        <button
          aria-label={`Go to ${moment.title}`}
          title="Wind the clock to this moment"
          className="shrink-0 text-[10px] uppercase tracking-wider text-mil-cyan hover:text-white"
          onClick={(e) => {
            e.preventDefault();
            c.focusMoment(moment.id);
          }}
        >
          Go to
        </button>
        <button
          aria-label={`Remove ${moment.title}`}
          className="shrink-0 px-1 text-mil-dim hover:text-mil-red"
          onClick={(e) => {
            e.preventDefault();
            c.removeMoment(moment.id);
          }}
        >
          ✕
        </button>
      </summary>
      {open && (
      <div className="space-y-2 border-t border-mil-border p-2">
        <Field label="Title">
          <input className={inputClass} value={moment.title} aria-label={`Title of moment ${index + 1}`} onChange={(e) => c.patchMoment(moment.id, { title: e.target.value })} />
        </Field>
        <Field label="Caption">
          <textarea
            className={cn(inputClass, 'h-14 resize-y leading-snug')}
            aria-label={`Caption of moment ${index + 1}`}
            value={moment.caption ?? ''}
            onChange={(e) => c.patchMoment(moment.id, { caption: e.target.value })}
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <NumField label="Comes up at (s)" value={moment.atS} min={0} max={duration} step={10} onCommit={(v) => v !== undefined && c.patchMoment(moment.id, { atS: v })} />
          <NumField label="Stays up for (s)" value={moment.holdS} min={MIN_HOLD_S} step={15} onCommit={(v) => v !== undefined && c.patchMoment(moment.id, { holdS: v })} />
        </div>
        <Field label="Hangs on">
          <Select
            value={moment.unitId ?? ''}
            onChange={(v) => c.patchMoment(moment.id, { unitId: v || undefined })}
            options={[{ value: '', label: 'A spot on the map' }, ...units.map((u) => ({ value: u.id, label: u.name }))]}
          />
        </Field>
        <PicturePicker moment={moment} />
      </div>
      )}
    </details>
  );
}

export function StoryboardPanel() {
  const c = useController();
  const open = useExercise((s) => s.storyOpen);
  const scenario = useExercise((s) => s.scenario);
  const showStory = useExercise((s) => s.view.showStory);
  const second = useClockSecond();
  const [blocked, setBlocked] = useState(false);
  const [count, setCount] = useState(14);
  if (!open) return null;
  const moments = scenario.storyboard ?? [];
  const problems = c.storyboardProblems();
  const bytes = imageBytes(moments);

  return (
    <div role="dialog" aria-label="Storyboard" className="pointer-events-auto absolute bottom-3 right-3 top-14 z-20 flex w-[460px] max-w-[calc(100%-1.5rem)] flex-col border border-mil-border bg-mil-panel/95 shadow-glass backdrop-blur">
      <div className="flex items-start justify-between gap-3 border-b border-mil-border p-4">
        <div>
          <h2 className="mil-label text-[11px]">Storyboard</h2>
          <p className="mt-1 text-[11px] leading-snug text-mil-text">
            Pictures and a line or two that come up beside a unit as the run plays, then go when their time is up. Build one from
            what happens in the run, then swap in your own pictures.
          </p>
        </div>
        <button aria-label="Close storyboard" className="text-mil-dim hover:text-white" onClick={() => c.toggleStoryboard(false)}>
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-24">
            <NumField label="Moments" value={count} min={1} max={60} step={2} onCommit={(v) => v !== undefined && setCount(Math.round(v))} />
          </div>
          <Button size="sm" onClick={() => c.generateStoryboard({ max: count })}>
            {moments.length ? 'Build it again' : 'Build from the run'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => c.addMoment()}>
            + Add at T+{formatClock(second)}
          </Button>
        </div>
        <p className="text-[10px] leading-snug text-mil-dim">
          Building picks the moments worth telling — losses, hits, contacts, launches — spreads them over the units, and puts a
          stock picture on each. It replaces whatever is there now.
        </p>

        <label className="flex items-center gap-2 text-[11px] text-mil-text">
          <input type="checkbox" checked={showStory} onChange={(e) => c.setView({ showStory: e.target.checked })} />
          Show the bubbles on the map
        </label>

        {problems.length > 0 && (
          <div role="alert" className="space-y-1 border border-mil-red/50 bg-mil-red/10 p-2 text-[11px] text-mil-red">
            {problems.slice(0, 4).map((p) => (
              <p key={p}>{p}</p>
            ))}
          </div>
        )}

        {moments.length === 0 ? (
          <p className="text-[11px] text-mil-dim">Nothing in the storyboard yet. Build one from the run, or add a moment at the time on the clock.</p>
        ) : (
          <Panel title={`${moments.length} moment${moments.length === 1 ? '' : 's'}`} className="space-y-1.5 p-2">
            {moments.map((m, i) => (
              <MomentCard key={m.id} moment={m} index={i} />
            ))}
          </Panel>
        )}

        {moments.length > 0 && (
          <div className="space-y-2 border-t border-mil-border pt-3">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => setBlocked(!openReport(storyboardHtml(scenario)))}>
                Storyboard to print
              </Button>
              <Button size="sm" variant="secondary" onClick={() => downloadText(`storyboard-${fileSafe(scenario.name)}.html`, 'text/html', storyboardHtml(scenario))}>
                Download the page
              </Button>
              <Button size="sm" variant="ghost" onClick={() => c.clearStoryboardImages()}>
                Clear every picture
              </Button>
            </div>
            {blocked && (
              <p role="alert" className="text-[10px] text-mil-amber">
                The browser blocked the window. Allow pop-ups for this page, or download the page instead.
              </p>
            )}
            <p className="text-[10px] leading-snug text-mil-dim">
              Pictures you capture or load are kept inside the scenario ({kb(bytes)} so far). Stock pictures are not, so they cost
              nothing to save. Over about 700 kB a scenario is too big for the shared library.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
