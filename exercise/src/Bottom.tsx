import { useEffect, useRef } from 'react';
import { cn } from './lib/cn';
import { Button } from './ui';
import { useClockSecond, useController, useExercise } from './context';
import { PLAYBACK_RATES } from './controller';
import { formatClock } from './geo';
import { momentsAt, scrollIntoViewSafely } from './storyboard';
import type { StoryMoment } from './types';
import { EVENT_COLOR } from './status';

/** One empty array for every scenario with no storyboard: a fresh [] in a selector would re-render without end. */
const NO_MOMENTS: StoryMoment[] = [];

function PlaybackBar() {
  const c = useController();
  const second = useClockSecond();
  const playing = useExercise((s) => s.playing);
  const rate = useExercise((s) => s.rate);
  const duration = useExercise((s) => s.active.scenario.durationS);
  const events = useExercise((s) => s.active.trajectory.events);
  const moments = useExercise((s) => s.active.scenario.storyboard) ?? NO_MOMENTS;
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
        {/* Storyboard beats, above the line: click one to wind the clock to it. */}
        {moments.length > 0 && (
          <div className="absolute inset-x-1.5 bottom-full mb-0.5 h-2">
            {moments.map((m) => (
              <button
                key={m.id}
                title={`T+${formatClock(m.atS)}  ${m.title}`}
                aria-label={`Storyboard moment: ${m.title}`}
                className="absolute top-0 h-2 w-1 -translate-x-1/2 bg-mil-cyan/70 hover:bg-mil-cyan"
                style={{ left: `${(m.atS / duration) * 100}%` }}
                onClick={() => c.focusMoment(m.id)}
              />
            ))}
          </div>
        )}
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

/**
 * The storyboard as a strip that runs with the clock: every beat in order, the one that is up lit and scrolled to. This is
 * the same storyboard the bubbles on the map come from, laid out so a room can follow it without opening a panel.
 */
function Story() {
  const c = useController();
  const second = useClockSecond();
  const moments = useExercise((s) => s.active.scenario.storyboard) ?? NO_MOMENTS;
  const live = new Set(momentsAt(moments, second).map((a) => a.moment.id));
  const strip = useRef<HTMLUListElement>(null);
  const current = moments.filter((m) => m.atS <= second).at(-1)?.id ?? moments[0]?.id;

  // Keep the beat that is up in view as the run plays, without fighting someone scrolling the strip by hand.
  useEffect(() => {
    if (!current) return;
    scrollIntoViewSafely(strip.current?.querySelector(`[data-moment="${current}"]`));
  }, [current]);

  if (moments.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center gap-3 p-4 text-[11px] text-mil-dim">
        <span>No storyboard yet. Build one from what happens in this run, with a picture on each moment.</span>
        <Button size="sm" onClick={() => c.toggleStoryboard(true)}>
          Open the storyboard
        </Button>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-hidden">
      <ul ref={strip} className="flex h-full items-stretch gap-2 overflow-x-auto p-2" aria-label="Storyboard">
        {moments.map((m, i) => {
          const up = live.has(m.id);
          const past = m.atS <= second;
          return (
            <li key={m.id} data-moment={m.id} className="shrink-0">
              <button
                aria-label={`Storyboard moment ${i + 1}: ${m.title}`}
                aria-current={up || undefined}
                onClick={() => c.focusMoment(m.id)}
                className={cn(
                  'flex h-full w-48 flex-col overflow-hidden border text-left transition-opacity',
                  up ? 'border-mil-cyan' : past ? 'border-mil-border' : 'border-mil-border opacity-50',
                )}
              >
                {m.image ? (
                  <img src={m.image} alt="" className="h-20 w-full shrink-0 object-cover" />
                ) : (
                  <span className="flex h-20 w-full shrink-0 items-center justify-center bg-mil-bg text-[9px] text-mil-dim">no picture</span>
                )}
                <span className="flex min-h-0 flex-1 flex-col gap-0.5 p-1.5">
                  <span className={cn('truncate text-[10px] font-medium uppercase tracking-wider', up ? 'text-mil-cyan' : 'text-white')}>{m.title}</span>
                  <span className="mil-value text-[9px] tabular-nums text-mil-dim">T+{formatClock(m.atS)}</span>
                  {m.caption && <span className="line-clamp-2 text-[10px] leading-snug text-mil-text">{m.caption}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Bottom() {
  const storyCount = useExercise((s) => s.active.scenario.storyboard?.length ?? 0);
  const c = useController();
  return (
    <div className="flex h-full flex-col">
      <PlaybackBar />
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-mil-border px-3 py-1.5">
        <h2 className="mil-label">Storyboard{storyCount ? ` · ${storyCount} moments` : ''}</h2>
        <button className="font-mono text-[10px] uppercase tracking-wider text-mil-dim hover:text-mil-cyan" onClick={() => c.toggleStoryboard(true)}>
          Edit
        </button>
      </div>
      <Story />
    </div>
  );
}
