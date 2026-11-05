import { cn } from '../../lib/cn';
import { Button } from '../../shell/ui';
import { AuthenticatedImage, GeoJsonDownload } from './media';
import { timeSpan } from './controller';
import { useController, useMissions } from './context';
import { CreateMissionForm, ImageUploadForm, ReportForm, TrackResult, TrackUploadForm } from './forms';
import { fmtClock, fmtDuration, fmtUtc, num } from './fmt';
import { ErrorLine, FollowToggle, Heading, Notice, ValidityBadge, ValidityReasons } from './parts';
import { DISCREPANCY_WARN_M, KIND_ICON, locateStyle } from './styling';
import type { StoryboardEvent } from './types';

export function MissionList() {
  const c = useController();
  const missions = useMissions((s) => s.missions);
  const id = useMissions((s) => s.missionId);
  return (
    <div>
      <Heading>Missions</Heading>
      {missions.length === 0 ? (
        <p className="text-[11px] text-mil-dim">No missions yet. Create one below.</p>
      ) : (
        <ul className="space-y-1">
          {missions.map((m) => (
            <li key={m.mission_id}>
              <button
                aria-pressed={m.mission_id === id}
                onClick={() => void c.selectMission(m.mission_id)}
                className={cn('w-full rounded-sm border px-2 py-1 text-left text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-mil-cyan/60', m.mission_id === id ? 'border-mil-cyan/60 bg-mil-cyan/10 text-white' : 'border-mil-border text-mil-text hover:text-white')}
              >
                <span className="block font-medium">{m.name}</span>
                <span className="text-mil-dim">
                  {m.vessel_id} - {m.fix_count} fixes, {m.media_count} images, {m.report_count} reports
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function StoryboardSidebar() {
  const error = useMissions((s) => s.error);
  const notice = useMissions((s) => s.notice);
  const busy = useMissions((s) => s.busy);
  const sample = useMissions((s) => s.sampleStoryboard);
  return (
    <div className="space-y-3">
      <MissionList />
      {busy && (
        <p role="status" className="text-[11px] text-mil-cyan">
          {busy}...
        </p>
      )}
      <ErrorLine text={error} />
      <Notice text={notice} />
      {sample && <p className="text-[11px] text-mil-amber">Sample data mode: forms are disabled because the backend is not available.</p>}
      <fieldset disabled={sample} className="space-y-4 border-0 p-0 disabled:opacity-50">
        <CreateMissionForm />
        <TrackUploadForm />
        <TrackResult />
        <ImageUploadForm />
        <ReportForm />
      </fieldset>
      <div className="lg:hidden">
        <EventDetail />
        <MissionSummary />
      </div>
    </div>
  );
}

export function MissionSummary() {
  const sb = useMissions((s) => s.storyboard);
  const sample = useMissions((s) => s.sampleStoryboard);
  if (!sb) return null;
  const st = sb.stats;
  const rows: [string, string][] = [
    ['Distance', `${num(st.distance_nm, 2)} nm`],
    ['Duration', fmtDuration(st.duration_s)],
    ['Fixes', String(st.fix_count)],
    ['Longest gap', fmtDuration(st.max_gap_s)],
    ['Gaps over limit', `${st.gaps_over_limit} (limit ${fmtDuration(sb.max_interp_gap_s)})`],
    ['Start', fmtUtc(st.start_utc)],
    ['End', fmtUtc(st.end_utc)],
  ];
  return (
    <section aria-label="Mission summary" className="mt-3">
      <Heading>Mission summary</Heading>
      <p className="mb-1 text-[11px] text-white">
        {sb.mission.name} <ValidityBadge validity={sb.validity} />
      </p>
      <ValidityReasons validity={sb.validity} />
      <dl className="mt-2 space-y-0.5 text-[11px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-mil-dim">{k}</dt>
            <dd className={cn('text-right text-white', k === 'Gaps over limit' && st.gaps_over_limit > 0 && 'text-mil-amber')}>{v}</dd>
          </div>
        ))}
      </dl>
      <GeoJsonDownload key={sb.mission.mission_id} missionId={sb.mission.mission_id} disabled={sample} />
    </section>
  );
}

export function EventDetail() {
  const sample = useMissions((s) => s.sampleStoryboard);
  const sb = useMissions((s) => s.storyboard);
  const id = useMissions((s) => s.selectedEventId);
  const ev = sb?.events.find((e) => e.event_id === id);
  if (!ev) return <p className="text-[11px] text-mil-dim">Select an event in the list or on the map to read it here.</p>;
  const l = ev.located;
  const st = locateStyle(l.method);
  return (
    <section aria-label="Event detail">
      <Heading>{ev.kind === 'image' ? 'Image' : 'Report'}</Heading>
      <p className="text-xs text-white">{ev.title}</p>
      <p className="text-[11px] text-mil-dim">{fmtUtc(ev.t_utc)}</p>
      {ev.kind === 'image' &&
        (ev.media_url ? (
          <AuthenticatedImage path={ev.media_url} alt={ev.title} sample={sample} />
        ) : (
          <p className="mt-2 text-[11px] text-mil-dim">No image bytes available for this event.</p>
        ))}
      {ev.body && <p className="mt-2 whitespace-pre-wrap text-[11px] text-mil-text">{ev.body}</p>}
      <p className="mt-2 text-[11px]">
        <span className="text-mil-dim">Located: </span>
        <span className="text-white">{st.label}</span> <ValidityBadge validity={l.validity} />
      </p>
      {st.warning && <p className="mt-1 text-[11px] text-mil-amber">{st.warning}</p>}
      <ValidityReasons validity={l.validity} />
      {l.lat != null && l.lon != null && (
        <p className="mt-1 text-[11px] text-mil-text">
          Track position {l.lat.toFixed(5)}, {l.lon.toFixed(5)}
          {l.distance_along_track_nm != null && `; ${l.distance_along_track_nm.toFixed(2)} nm along track`}
          {l.sog_kt != null && `; ${l.sog_kt.toFixed(1)} kt`}
        </p>
      )}
      {l.discrepancy_m != null && (
        <p className={cn('mt-1 text-[11px]', l.discrepancy_m > DISCREPANCY_WARN_M ? 'text-mil-amber' : 'text-mil-text')}>
          Stated position ({l.stated_source ?? 'unknown source'}) differs from the track by {Math.round(l.discrepancy_m)} m
          {l.stated_lat != null && l.stated_lon != null && ` (stated ${l.stated_lat.toFixed(5)}, ${l.stated_lon.toFixed(5)})`}.
        </p>
      )}
    </section>
  );
}

export function StoryboardSide() {
  return (
    <div className="space-y-3">
      <EventDetail />
      <MissionSummary />
      <section aria-label="Map key" className="text-[11px] text-mil-text">
        <Heading>Key</Heading>
        <ul className="space-y-0.5">
          <li>Blue line: recorded track geometry (thin grey: segment includes a gap or unverified coverage)</li>
          <li>Cyan marker: image; amber marker: report</li>
          <li>Large marker: exact fix; smaller: interpolated; amber ring: stated position far from track</li>
          <li>White arrow-point: ship at the scrubber time (hidden where position is not established)</li>
          <li>Events in a gap, before or after the track, or with no time have no marker.</li>
        </ul>
        <FollowToggle label="Keep the ship centered (the map shows about 8 km at a time)" />
      </section>
    </div>
  );
}

function EventRow({ e, selected, current, onPick }: { e: StoryboardEvent; selected: boolean; current: boolean; onPick: () => void }) {
  const st = locateStyle(e.located.method);
  return (
    <li>
      <button
        onClick={onPick}
        aria-current={current ? 'true' : undefined}
        aria-pressed={selected}
        className={cn(
          'flex w-full items-start gap-2 border-l-2 px-2 py-1 text-left text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-mil-cyan/60',
          selected ? 'border-mil-cyan bg-mil-cyan/15 text-white' : current ? 'border-mil-amber bg-mil-amber/10 text-white' : 'border-transparent text-mil-text hover:bg-mil-border/20',
        )}
      >
        <span aria-hidden className={e.kind === 'image' ? 'text-mil-cyan' : 'text-mil-amber'}>
          {KIND_ICON[e.kind]}
        </span>
        <span className="w-24 shrink-0 text-mil-dim">{e.t_utc ? fmtUtc(e.t_utc).slice(11) : 'no time'}</span>
        <span className="min-w-0 flex-1 truncate">
          <span className="sr-only">{e.kind}: </span>
          {e.title}
        </span>
        {st.warning ? (
          <span className="shrink-0 text-mil-amber" title={st.warning}>
            {'⚠'} {st.label}: position not established
          </span>
        ) : (
          <span className="shrink-0 text-mil-dim">
            {st.label}
            {e.located.discrepancy_m != null && e.located.discrepancy_m > DISCREPANCY_WARN_M && <span className="text-mil-amber"> {'⚠'} {Math.round(e.located.discrepancy_m)} m off</span>}
          </span>
        )}
      </button>
    </li>
  );
}

export function Scrubber() {
  const c = useController();
  const sb = useMissions((s) => s.storyboard);
  const ms = useMissions((s) => s.scrubMs);
  const pos = useMissions((s) => s.shipPosition);
  const span = sb ? timeSpan(sb) : null;
  if (!sb || !span || ms == null) return <p className="p-3 text-[11px] text-mil-dim">Select a mission with a track to use the timeline.</p>;
  const text = pos?.established
    ? `ship at ${pos.lat?.toFixed(5)}, ${pos.lon?.toFixed(5)} (${pos.method === 'exact_fix' ? 'exact fix' : 'interpolated'})`
    : `position not established${pos?.reason ? `: ${pos.reason}` : ''}`;
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <Button size="sm" variant="secondary" aria-label="Previous event" onClick={() => c.stepEvent(-1)}>
        {'◀'}
      </Button>
      <input
        type="range"
        aria-label="Mission time"
        aria-valuetext={`${fmtClock(ms)}, ${text}`}
        className="min-w-0 flex-1 accent-cyan-400"
        min={span.startMs}
        max={span.endMs}
        step={1000}
        value={ms}
        onChange={(e) => c.setScrub(Number(e.target.value))}
      />
      <Button size="sm" variant="secondary" aria-label="Next event" onClick={() => c.stepEvent(1)}>
        {'▶'}
      </Button>
      <div className="w-56 shrink-0 text-[11px]" aria-live="off">
        <div className="text-white">{fmtClock(ms)}</div>
        <div className={pos?.established ? 'text-mil-text' : 'text-mil-amber'}>{text}</div>
      </div>
    </div>
  );
}

export function StoryboardBottom() {
  const c = useController();
  const sb = useMissions((s) => s.storyboard);
  const selected = useMissions((s) => s.selectedEventId);
  const ms = useMissions((s) => s.scrubMs);
  const current = sb && ms != null ? c.currentEventId() : null;
  return (
    <div className="flex h-full flex-col">
      <Scrubber />
      <ul aria-label="Events" className="min-h-0 flex-1 overflow-y-auto border-t border-mil-border">
        {sb?.events.length === 0 && <li className="p-3 text-[11px] text-mil-dim">No images or reports yet.</li>}
        {sb?.events.map((e) => (
          <EventRow key={e.event_id} e={e} selected={e.event_id === selected} current={e.event_id === current} onPick={() => c.selectEvent(e.event_id)} />
        ))}
      </ul>
    </div>
  );
}
