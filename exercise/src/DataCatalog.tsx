import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from './lib/cn';
import { Button } from './ui';
import { useController, useExercise } from './context';
import { catalogOf, deriveRecords, FEEDS, recordsForEvent } from './datasources';
import type { DataRecord, FeedId } from './datasources';
import { formatClock } from './geo';
import { scrollIntoViewSafely } from './storyboard';

/**
 * The collection sources behind the picture: which feeds are reporting in this run, how much each one carries, and the
 * record any single event came from. The records are built from the simulation's own geometry — nothing here is a real
 * observation, and every feed says what it was derived from.
 */

const DISCIPLINE_COLOR: Record<string, string> = {
  RADAR: '#00e5ff',
  ACOUSTIC: '#00e676',
  SIGINT: '#ffc107',
  COMMS: '#8ba4c4',
  IMINT: '#c792ea',
  SYSTEM: '#7390b0',
};

function RecordCard({ record, name }: { record: DataRecord; name: (id: string) => string }) {
  const feed = FEEDS.find((f) => f.id === record.feed);
  return (
    <article className="border border-mil-border bg-mil-bg/50">
      <header className="flex items-baseline justify-between gap-2 border-b border-mil-border px-3 py-1.5">
        <h4 className="min-w-0 truncate text-[11px] text-white">{record.title}</h4>
        <span className="mil-value shrink-0 text-[10px] tabular-nums text-mil-dim">T+{formatClock(record.tS)}</span>
      </header>
      <div className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-2 text-[9px] uppercase tracking-wider">
          <span className="border px-1 py-0.5" style={{ borderColor: `${DISCIPLINE_COLOR[feed?.discipline ?? 'SYSTEM']}66`, color: DISCIPLINE_COLOR[feed?.discipline ?? 'SYSTEM'] }}>
            {feed?.discipline}
          </span>
          <span className="text-mil-dim">{feed?.label}</span>
          {record.byUnitId && <span className="text-mil-dim">collected by {name(record.byUnitId)}</span>}
        </div>
        {record.fields.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
            {record.fields.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <dt className="truncate text-mil-dim">{k}</dt>
                <dd className="truncate text-right text-white">{v}</dd>
              </div>
            ))}
          </dl>
        )}
        <details>
          <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-mil-cyan">Raw record</summary>
          <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words border border-mil-border bg-mil-bg p-2 text-[10px] leading-snug text-mil-text">
            {record.raw}
          </pre>
        </details>
      </div>
    </article>
  );
}

export function DataCatalog() {
  const c = useController();
  const open = useExercise((s) => s.catalogOpen);
  const presenting = useExercise((s) => s.presenting);
  const eventIndex = useExercise((s) => s.catalogEventIndex);
  const run = useExercise((s) => s.active);
  const [feedId, setFeedId] = useState<FeedId | null>(null);
  const body = useRef<HTMLDivElement>(null);

  const records = useMemo(() => (open ? deriveRecords(run.scenario, run.trajectory) : []), [open, run]);
  const entries = useMemo(() => (open ? catalogOf(run.scenario, records) : []), [open, run.scenario, records]);
  const name = (id: string) => run.scenario.units.find((u) => u.id === id)?.name ?? id;

  // Opening on an event means showing that event's records, not the list of feeds.
  useEffect(() => {
    if (eventIndex !== null) setFeedId(null);
  }, [eventIndex]);
  useEffect(() => {
    if (open) scrollIntoViewSafely(body.current);
  }, [open, feedId, eventIndex]);

  if (!open || presenting) return null;

  const event = eventIndex !== null ? run.trajectory.events[eventIndex] : undefined;
  const forEvent = eventIndex !== null ? recordsForEvent(records, eventIndex) : [];
  const feedRecords = feedId ? records.filter((r) => r.feed === feedId) : [];
  const feed = feedId ? FEEDS.find((f) => f.id === feedId) : undefined;

  return (
    <div
      role="dialog"
      aria-label="Data catalog"
      className="pointer-events-auto absolute bottom-3 right-3 top-14 z-20 flex w-[520px] max-w-[calc(100%-1.5rem)] flex-col border border-mil-border bg-mil-panel/95 shadow-glass backdrop-blur"
    >
      <div className="flex items-start justify-between gap-3 border-b border-mil-border p-4">
        <div className="min-w-0">
          <h2 className="mil-label text-[11px]">Data catalog</h2>
          <p className="mt-1 text-[11px] leading-snug text-mil-text">
            The sources feeding this picture, and the record behind any event. Every record is synthesised from the
            simulation’s own geometry and timing; none of it is a real observation.
          </p>
        </div>
        <Button size="sm" variant="ghost" aria-label="Close the data catalog" onClick={() => c.toggleCatalog(false)}>
          Close
        </Button>
      </div>

      <div ref={body} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {event && (
          <section className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="mil-label">Source of this event</h3>
              <button className="text-[10px] uppercase tracking-wider text-mil-dim hover:text-white" onClick={() => c.toggleCatalog(true)}>
                All sources
              </button>
            </div>
            <p className="text-[11px] text-mil-text">
              <span className="mil-value mr-2 tabular-nums">T+{formatClock(event.tS)}</span>
              {forEvent.length} record{forEvent.length === 1 ? '' : 's'} reported this.
            </p>
            {forEvent.length === 0 ? (
              <p className="text-[11px] text-mil-dim">
                No feed carries this one: it is a change of state inside the simulation rather than something a sensor or a
                message would report.
              </p>
            ) : (
              forEvent.map((r) => <RecordCard key={r.id} record={r} name={name} />)
            )}
          </section>
        )}

        {!event && feed && (
          <section className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="mil-label">{feed.label}</h3>
              <button className="text-[10px] uppercase tracking-wider text-mil-dim hover:text-white" onClick={() => setFeedId(null)}>
                All sources
              </button>
            </div>
            <p className="text-[11px] leading-snug text-mil-dim">{feed.derivedFrom}</p>
            {feedRecords.length === 0 ? (
              <p className="text-[11px] text-mil-dim">Nothing in this run comes from this source.</p>
            ) : (
              <ul className="space-y-2">
                {feedRecords.slice(0, 50).map((r) => (
                  <li key={r.id}>
                    <RecordCard record={r} name={name} />
                  </li>
                ))}
                {feedRecords.length > 50 && (
                  <li className="text-[10px] text-mil-dim">{feedRecords.length - 50} more, not listed.</li>
                )}
              </ul>
            )}
          </section>
        )}

        {!event && !feed && (
          <section className="space-y-2">
            <h3 className="mil-label">Sources in this run</h3>
            <ul className="space-y-1.5" aria-label="Data sources">
              {entries.map((entry) => (
                <li key={entry.feed.id}>
                  <button
                    disabled={entry.records === 0}
                    onClick={() => setFeedId(entry.feed.id)}
                    className={cn(
                      'w-full border px-3 py-2 text-left',
                      entry.records === 0
                        ? 'cursor-default border-mil-border/50 opacity-50'
                        : 'border-mil-border hover:border-mil-cyan/60',
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="flex min-w-0 items-baseline gap-2">
                        <span
                          className="shrink-0 border px-1 py-0.5 text-[9px] uppercase tracking-wider"
                          style={{ borderColor: `${DISCIPLINE_COLOR[entry.feed.discipline]}66`, color: DISCIPLINE_COLOR[entry.feed.discipline] }}
                        >
                          {entry.feed.discipline}
                        </span>
                        <span className="truncate text-[11px] text-white">{entry.feed.label}</span>
                      </span>
                      <span className="mil-value shrink-0 text-[10px] tabular-nums text-mil-dim">
                        {entry.records === 0 ? 'none' : `${entry.records} records`}
                      </span>
                    </span>
                    <span className="mt-1 block text-[10px] leading-snug text-mil-dim">{entry.feed.blurb}</span>
                    {entry.records > 0 && (
                      <span className="mt-1 block text-[10px] text-mil-dim">
                        {entry.firstS !== null && entry.lastS !== null && (
                          <span className="mil-value tabular-nums">
                            T+{formatClock(entry.firstS)} to T+{formatClock(entry.lastS)}
                          </span>
                        )}
                        {entry.platforms.length > 0 && <span> · {entry.platforms.slice(0, 3).map(name).join(', ')}{entry.platforms.length > 3 ? ` +${entry.platforms.length - 3}` : ''}</span>}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            <p className="pt-1 text-[10px] leading-snug text-mil-dim">
              {records.length} records in all. Pick a source to read them, or press Source on any line of the event feed to
              see what reported it.
            </p>
          </section>
        )}
      </div>
    </div>
  );
}
