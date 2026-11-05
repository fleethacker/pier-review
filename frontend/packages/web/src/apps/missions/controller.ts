import type { AppHost } from '../../scene/app';
import { authHeaders, describeError } from '../mooring/api';
import {
  ApiError,
  buildMediaForm,
  buildTrackForm,
  isUnavailable,
  serviceUrl,
  missionsApi,
  runTransit,
  type MediaFormInput,
  type TrackFormInput,
} from './api';
import { prepareTrack, locateOnTrack, currentEventIndex, type TimedFix, type TrackPosition } from './geo';
import { advanceClock, clampSpeed, endTime, stateAt, trailPoints, type Clock } from './playback';
import { sampleResponse, samplePreset, sampleSeries, sampleStoryboard } from './fixtures';
import {
  VESSEL_COLORS,
  centroid,
  eventIdFromEntity,
  makeProjector,
  shipMarker,
  storyboardContent,
  trailLinks,
  tugVector,
  vesselEntities,
  type Projector,
  type VesselLook,
  SHIP_ID,
} from './scene';
import { Store } from './store';
import { hasMarker } from './styling';
import { parseRequestText, setMaxSpeed, setRouteSpeed, setVesselMode } from './transitRequest';
import type {
  Mission,
  ReportCreate,
  Storyboard,
  TrackIngestResult,
  TransitPreset,
  TransitRequest,
  TransitResponse,
  TransitSeries,
  TransitVesselState,
  VesselTransit,
} from './types';

export type Tab = 'storyboard' | 'transit';

export interface MissionsState {
  tab: Tab;
  sampleStoryboard: boolean;
  sampleTransit: boolean;
  // storyboard
  missions: Mission[];
  missionId: string | null;
  storyboard: Storyboard | null;
  busy: string | null;
  error: string | null;
  notice: string | null;
  trackResult: TrackIngestResult | null;
  scrubMs: number | null;
  selectedEventId: string | null;
  shipPosition: TrackPosition | null;
  // transit
  presets: TransitPreset[];
  presetId: string | null;
  request: TransitRequest | null;
  requestText: string;
  requestError: string | null;
  running: boolean;
  progress: number;
  response: TransitResponse | null;
  series: TransitSeries | null;
  transitError: string | null;
  transitNotice: string | null;
  clock: Clock;
  vessels: TransitVesselState[];
  selectedVesselId: string | null;
}

const initial: MissionsState = {
  tab: 'storyboard',
  sampleStoryboard: false,
  sampleTransit: false,
  missions: [],
  missionId: null,
  storyboard: null,
  busy: null,
  error: null,
  notice: null,
  trackResult: null,
  scrubMs: null,
  selectedEventId: null,
  shipPosition: null,
  presets: [],
  presetId: null,
  request: null,
  requestText: '',
  requestError: null,
  running: false,
  progress: 0,
  response: null,
  series: null,
  transitError: null,
  transitNotice: null,
  clock: { t: 0, playing: false, speed: 10 },
  vessels: [],
  selectedVesselId: null,
};

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/** Span of the scrubber: the track plus any timed events (so events outside the track can be visited and shown unlocated). */
export function timeSpan(sb: Storyboard): { startMs: number; endMs: number } | null {
  const times = [...sb.track.map((f) => Date.parse(f.t_utc)), ...sb.events.map((e) => (e.t_utc ? Date.parse(e.t_utc) : NaN))].filter(Number.isFinite);
  if (!times.length) return null;
  return { startMs: Math.min(...times), endMs: Math.max(...times) };
}

export class MissionsController {
  readonly store = new Store<MissionsState>({ ...initial });
  private timed: TimedFix[] = [];
  private projector: Projector | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private lastTick = 0;
  private abort: AbortController | null = null;
  private unsubScene: () => void;
  private disposed = false;
  private looks = new Map<string, VesselLook>();
  private lengths = new Map<string, number>();

  constructor(private host: AppHost) {
    this.unsubScene = host.store.subscribe(() => {
      const sel = host.store.getState().selection;
      if (this.store.getState().tab !== 'storyboard' || sel?.type !== 'entity') return;
      const id = eventIdFromEntity(sel.id);
      if (id && id !== this.store.getState().selectedEventId) this.selectEvent(id);
    });
  }

  get state(): MissionsState {
    return this.store.getState();
  }

  async init(): Promise<void> {
    await Promise.all([this.refreshMissions(), this.loadPresets()]);
    this.renderScene();
  }

  dispose(): void {
    this.disposed = true;
    this.pause();
    this.abort?.abort();
    this.unsubScene();
    this.host.store.clear();
  }

  // ---- tabs ----
  setTab(tab: Tab): void {
    if (tab === this.state.tab) return;
    if (tab === 'storyboard') this.pause();
    this.store.setState({ tab });
    this.renderScene();
  }

  // ---- storyboard ----
  async refreshMissions(selectId?: string): Promise<void> {
    try {
      const missions = await missionsApi.listMissions();
      this.store.setState({ missions, sampleStoryboard: false, error: null });
      const pick = selectId ?? this.state.missionId ?? missions[0]?.mission_id ?? null;
      if (pick && missions.some((m) => m.mission_id === pick)) await this.selectMission(pick);
    } catch (e) {
      if (isUnavailable(e)) this.enterSampleStoryboard();
      else this.store.setState({ error: describeError(e) });
    }
  }

  enterSampleStoryboard(): void {
    this.store.setState({ sampleStoryboard: true, missions: [sampleStoryboard.mission], error: null, trackResult: null });
    this.applyStoryboard(sampleStoryboard);
  }

  async selectMission(id: string): Promise<void> {
    if (this.state.sampleStoryboard) {
      this.applyStoryboard(sampleStoryboard);
      return;
    }
    this.store.setState({ missionId: id, busy: 'Loading storyboard', error: null });
    try {
      const sb = await missionsApi.storyboard(id);
      if (this.disposed) return;
      this.applyStoryboard(sb);
    } catch (e) {
      this.store.setState({ error: describeError(e), storyboard: null });
    } finally {
      this.store.setState({ busy: null });
    }
  }

  private applyStoryboard(sb: Storyboard): void {
    this.timed = prepareTrack(sb.track);
    const span = timeSpan(sb);
    const start = span?.startMs ?? null;
    const keepSel = sb.events.some((e) => e.event_id === this.state.selectedEventId) ? this.state.selectedEventId : null;
    this.store.setState({ storyboard: sb, missionId: sb.mission.mission_id, scrubMs: start, selectedEventId: keepSel });
    this.updateShip();
    if (this.state.tab === 'storyboard') this.renderScene();
  }

  /** Reload the current mission's storyboard after an upload. */
  private async reload(): Promise<void> {
    const id = this.state.missionId;
    if (id) await this.refreshMissions(id);
  }

  setScrub(ms: number): void {
    this.store.setState({ scrubMs: ms });
    this.updateShip();
  }

  selectEvent(eventId: string | null): void {
    const sb = this.state.storyboard;
    const ev = sb?.events.find((e) => e.event_id === eventId);
    this.store.setState({ selectedEventId: eventId });
    if (ev?.t_utc) this.setScrub(Date.parse(ev.t_utc));
    if (this.state.tab === 'storyboard') {
      this.renderEventMarkers();
      this.host.store.select(ev && hasMarker(ev) ? { type: 'entity', id: `event:${ev.event_id}` } : null);
    }
  }

  stepEvent(delta: 1 | -1): void {
    const sb = this.state.storyboard;
    if (!sb || sb.events.length === 0) return;
    const times = sb.events.map((e) => (e.t_utc ? Date.parse(e.t_utc) : null));
    const cur = this.state.selectedEventId ? sb.events.findIndex((e) => e.event_id === this.state.selectedEventId) : currentEventIndex(times, this.state.scrubMs ?? -Infinity);
    const timedIdx = sb.events.map((_, i) => i).filter((i) => times[i] != null);
    const pos = timedIdx.indexOf(cur);
    const next = timedIdx[Math.min(timedIdx.length - 1, Math.max(0, (pos < 0 ? (delta > 0 ? -1 : timedIdx.length) : pos) + delta))];
    if (next != null) this.selectEvent(sb.events[next].event_id);
  }

  /** The event the scrubber has most recently passed. */
  currentEventId(): string | null {
    const sb = this.state.storyboard;
    if (!sb || this.state.scrubMs == null) return null;
    const i = currentEventIndex(sb.events.map((e) => (e.t_utc ? Date.parse(e.t_utc) : null)), this.state.scrubMs);
    return i < 0 ? null : sb.events[i].event_id;
  }

  private updateShip(): void {
    const sb = this.state.storyboard;
    const ms = this.state.scrubMs;
    if (!sb || ms == null) {
      this.store.setState({ shipPosition: null });
      return;
    }
    const pos = locateOnTrack(this.timed, ms, sb.max_interp_gap_s);
    this.store.setState({ shipPosition: pos });
    if (this.state.tab !== 'storyboard' || !this.projector) return;
    if (pos.established && pos.lat != null && pos.lon != null) {
      this.host.store.replaceEntitiesOfKind(['ship-marker'], [shipMarker(pos.lat, pos.lon, pos.headingDeg ?? null, this.projector, sb.mission.vessel_id)]);
    } else {
      this.host.store.replaceEntitiesOfKind(['ship-marker'], []);
    }
  }

  private renderEventMarkers(): void {
    const sb = this.state.storyboard;
    if (!sb || !this.projector) return;
    const { entities } = storyboardContent(sb, this.projector, this.state.selectedEventId);
    this.host.store.replaceEntitiesOfKind(['event-image', 'event-report'], entities);
  }

  private guard<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    if (this.state.sampleStoryboard) {
      this.store.setState({ error: 'Sample data mode: the backend is unavailable, so nothing can be saved.' });
      return Promise.resolve(undefined);
    }
    this.store.setState({ busy: label, error: null, notice: null });
    return fn()
      .catch((e: unknown) => {
        this.store.setState({ error: describeError(e) });
        return undefined;
      })
      .finally(() => this.store.setState({ busy: null }));
  }

  async createMission(name: string, vesselId: string, shipClassId?: string, description?: string): Promise<Mission | undefined> {
    const m = await this.guard('Creating mission', () =>
      missionsApi.createMission({ name, vessel_id: vesselId, ...(shipClassId ? { ship_class_id: shipClassId } : {}), ...(description ? { description } : {}) }),
    );
    if (m) await this.refreshMissions(m.mission_id);
    return m;
  }

  async uploadTrack(input: TrackFormInput): Promise<void> {
    const id = this.state.missionId;
    if (!id) return;
    const r = await this.guard('Uploading track', () => missionsApi.ingestTrackFile(id, buildTrackForm(input)));
    if (r) {
      this.store.setState({ trackResult: r });
      await this.reload();
    }
  }

  async uploadImage(input: MediaFormInput): Promise<void> {
    const id = this.state.missionId;
    if (!id) return;
    const r = await this.guard('Uploading image', () => missionsApi.uploadMedia(id, buildMediaForm(input)));
    if (r) {
      this.store.setState({ notice: `Image added (${r.time_note ?? (r.captured_utc ? 'time ' + r.captured_utc : 'no usable time')}).` });
      await this.reload();
    }
  }

  async addReport(r: ReportCreate): Promise<void> {
    const id = this.state.missionId;
    if (!id) return;
    const out = await this.guard('Adding report', () => missionsApi.addReport(id, r));
    if (out) {
      this.store.setState({ notice: 'Report added.' });
      await this.reload();
    }
  }

  // ---- transit ----
  async loadPresets(): Promise<void> {
    try {
      const presets = await missionsApi.listPresets();
      this.store.setState({ presets, sampleTransit: false });
      if (presets[0]) this.selectPreset(presets[0].preset_id);
    } catch (e) {
      if (isUnavailable(e)) {
        this.store.setState({ presets: [samplePreset], sampleTransit: true });
        this.selectPreset(samplePreset.preset_id);
      } else this.store.setState({ transitError: describeError(e) });
    }
  }

  selectPreset(id: string): void {
    const p = this.state.presets.find((x) => x.preset_id === id);
    if (!p) return;
    this.setRequest(structuredClone(p.request));
    this.store.setState({ presetId: id });
  }

  private setRequest(request: TransitRequest): void {
    this.store.setState({ request, requestText: JSON.stringify(request, null, 2), requestError: null });
  }

  editVessel(idx: number, change: { mode?: VesselTransit['mode']; maxSpeedKt?: number | null; routeSpeed?: { wp: number; kt: number } }): void {
    let r = this.state.request;
    if (!r) return;
    if (change.mode) r = setVesselMode(r, idx, change.mode);
    if (change.maxSpeedKt !== undefined) r = setMaxSpeed(r, idx, change.maxSpeedKt);
    if (change.routeSpeed) r = setRouteSpeed(r, idx, change.routeSpeed.wp, change.routeSpeed.kt);
    this.setRequest(r);
  }

  setRequestText(text: string): void {
    const parsed = parseRequestText(text);
    if ('error' in parsed) this.store.setState({ requestText: text, requestError: parsed.error });
    else this.store.setState({ requestText: text, request: parsed.request, requestError: null });
  }

  async run(): Promise<void> {
    const req = this.state.request;
    if (!req || this.state.requestError || this.state.running) return;
    this.pause();
    this.abort?.abort();
    this.abort = new AbortController();
    this.store.setState({ running: true, progress: 0, transitError: null, transitNotice: null, response: null, series: null, vessels: [] });
    try {
      let response: TransitResponse;
      let series: TransitSeries;
      if (this.state.sampleTransit) {
        response = sampleResponse;
        series = sampleSeries;
      } else {
        try {
          response = await runTransit(req, (progress) => this.store.setState({ progress }), this.abort.signal);
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 501) && !isUnavailable(e)) throw e;
          this.store.setState({ sampleTransit: true });
          response = sampleResponse;
          series = sampleSeries;
          return this.finishRun(response, series);
        }
        series = await missionsApi.series(response.result.series_url);
      }
      this.finishRun(response, series);
    } catch (e) {
      this.store.setState({ transitError: describeError(e) });
    } finally {
      this.store.setState({ running: false });
    }
  }

  private finishRun(response: TransitResponse, series: TransitSeries): void {
    this.store.setState({ response, series, clock: { t: 0, playing: false, speed: this.state.clock.speed }, selectedVesselId: series.frames[0]?.vessels[0]?.vessel_id ?? null });
    this.looks = new Map(response.result.vessels.map((v, i) => [v.vessel_id, { lengthM: this.lengths.get(v.ship_class_id) ?? null, color: VESSEL_COLORS[i % VESSEL_COLORS.length] }]));
    this.updateVessels();
    if (this.state.tab === 'transit') this.renderScene();
    void this.fetchLengths(response);
  }

  /** Best effort: the ship class gives LOA for a scaled hull outline. Failure keeps the labeled fixed glyph. */
  private async fetchLengths(response: TransitResponse): Promise<void> {
    if (this.state.sampleTransit) return;
    const ids = [...new Set(response.result.vessels.map((v) => v.ship_class_id))];
    await Promise.all(
      ids.map(async (id) => {
        try {
          const res = await fetch(serviceUrl(`/api/v1/ships/${encodeURIComponent(id)}`), { headers: authHeaders() });
          if (!res.ok) return;
          const loa = ((await res.json()) as { loa_ft?: number }).loa_ft;
          if (typeof loa === 'number' && loa > 0) this.lengths.set(id, loa * 0.3048);
        } catch {
          /* keep the fixed glyph */
        }
      }),
    );
    if (this.disposed || this.state.response !== response) return;
    this.looks = new Map(response.result.vessels.map((v, i) => [v.vessel_id, { lengthM: this.lengths.get(v.ship_class_id) ?? null, color: VESSEL_COLORS[i % VESSEL_COLORS.length] }]));
    this.pushTransit();
  }

  private updateVessels(): void {
    const series = this.state.series;
    this.store.setState({ vessels: series ? stateAt(series.frames, this.state.clock.t) : [] });
    this.pushTransit();
  }

  setPlayhead(t: number): void {
    const end = this.series() ? endTime(this.series()!.frames) : 0;
    this.store.setState({ clock: { ...this.state.clock, t: Math.min(end, Math.max(0, t)) } });
    this.updateVessels();
  }

  setSpeed(speed: number): void {
    this.store.setState({ clock: { ...this.state.clock, speed: clampSpeed(speed) } });
  }

  private series(): TransitSeries | null {
    return this.state.series;
  }

  play(): void {
    const series = this.state.series;
    if (!series || this.timer) return;
    const end = endTime(series.frames);
    const c = this.state.clock;
    this.store.setState({ clock: { ...c, t: c.t >= end ? 0 : c.t, playing: true } });
    this.lastTick = Date.now();
    // Reduced motion: step once a second instead of animating smoothly.
    this.timer = setInterval(() => this.tick(), prefersReducedMotion() ? 1000 : 100);
  }

  pause(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.state.clock.playing) this.store.setState({ clock: { ...this.state.clock, playing: false } });
  }

  private tick(): void {
    const series = this.state.series;
    if (!series) return this.pause();
    const now = Date.now();
    const dt = (now - this.lastTick) / 1000;
    this.lastTick = now;
    const next = advanceClock(this.state.clock, dt, endTime(series.frames));
    this.store.setState({ clock: next });
    this.updateVessels();
    if (!next.playing) this.pause();
  }

  selectVessel(id: string): void {
    this.store.setState({ selectedVesselId: id });
  }

  /** Jump to a transit event. */
  seekEvent(tS: number): void {
    this.setPlayhead(tS);
  }

  /** Create a mission per vessel and load its simulated track so it can be opened in the Storyboard tab. */
  async saveAsMission(): Promise<void> {
    const res = this.state.response;
    if (!res) return;
    if (this.state.sampleTransit) {
      this.store.setState({ transitError: 'Sample data mode: the backend is unavailable, so missions cannot be created.' });
      return;
    }
    this.store.setState({ busy: 'Saving missions', transitError: null, transitNotice: null });
    try {
      const made: string[] = [];
      for (const v of res.result.vessels) {
        const m = await missionsApi.createMission({
          name: `Simulated transit ${v.vessel_id}`,
          vessel_id: v.vessel_id,
          ship_class_id: v.ship_class_id,
          description: `Simulated (surrogate model, assumed propulsion), ${v.mode}, from transit result ${res.result_id}. Not a recorded track.`,
        });
        await missionsApi.ingestTrackJson(m.mission_id, v.track);
        made.push(m.mission_id);
      }
      this.store.setState({ transitNotice: `Saved ${made.length} mission(s). Opened in Storyboard.` });
      this.store.setState({ tab: 'storyboard' });
      await this.refreshMissions(made[0]);
      this.renderScene();
    } catch (e) {
      this.store.setState({ transitError: describeError(e) });
    } finally {
      this.store.setState({ busy: null });
    }
  }

  // ---- scene ----
  /** Rebuild everything on the map for the active tab (refits the camera). */
  renderScene(): void {
    const s = this.host.store;
    if (this.state.tab === 'storyboard') {
      const sb = this.state.storyboard;
      if (!sb || sb.track.length === 0) {
        this.projector = null;
        s.clear();
        return;
      }
      const c = centroid(sb.track);
      this.projector = makeProjector(c.lat, c.lon);
      const { entities, links } = storyboardContent(sb, this.projector, this.state.selectedEventId);
      s.setContent({ frame: this.projector.frame, entities, links, vectors: [] });
      this.updateShip();
    } else {
      const series = this.state.series;
      const first = series?.frames[0]?.vessels ?? [];
      if (!series || first.length === 0) {
        this.projector = null;
        s.clear();
        return;
      }
      const c = centroid(series.frames.flatMap((f) => f.vessels));
      this.projector = makeProjector(c.lat, c.lon);
      s.setContent({ frame: this.projector.frame, entities: [], links: [], vectors: [] });
      this.pushTransit();
    }
  }

  private pushTransit(): void {
    if (this.state.tab !== 'transit' || !this.projector || !this.state.series) return;
    const { vessels, series, clock } = this.state;
    const p = this.projector;
    const s = this.host.store;
    s.replaceEntitiesOfKind(['vessel', 'vessel-marker'], vesselEntities(vessels, p, this.looks));
    s.setLinks(vessels.flatMap((v) => trailLinks(v.vessel_id, trailPoints(series.frames, v.vessel_id, clock.t, { lat: v.lat, lon: v.lon }), p, this.looks.get(v.vessel_id)?.color ?? '#fff')));
    s.setVectors(vessels.flatMap((v) => (v.tugs ?? []).map((t) => tugVector(t, v, p))));
  }
}

export { SHIP_ID };
