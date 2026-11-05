import { Store } from '../../lib/store';
import type { AppHost } from '../../scene/app';
import { destination, offsetM } from './geo';
import type { MapStyleId } from './mapStyles';
import { DEFAULT_VIEW } from './scene';
import type { RunTrack, ViewOptions } from './scene';
import { PRESET_SCENARIOS, blankScenario, clone } from './scenarios';
import { exportScenario, parseScenario } from './scenarioJson';
import { SHIP_CLASSES, isMissile, isPlatform } from './ships';
import { defaultRedTeam, prepareRun, runMonteCarlo, validateRedTeam } from './montecarlo';
import type { McResult } from './montecarlo';
import { runTracks } from './scene';
import { runScenario, statesAt, validateScenario } from './sim';
import { autoStoryboard, defaultHoldS, inOrder, nextMomentId, validateStoryboard } from './storyboard';
import type { AutoOptions } from './storyboard';
import { pickStock, stock } from './stockImages';
import type { Trajectory } from './sim';
import type { Behavior, ClassId, Environment, LonLat, RedTeamSpec, ScenarioConfig, StoryMoment, UnitConfig, UnitState, Waypoint } from './types';

export type FollowMode = 'off' | 'follow' | 'chase' | 'orbit';
export const PLAYBACK_RATES = [1, 5, 10, 30, 60, 120, 300, 600];

/** Simulated time, advanced by wall-clock time times the playback rate. */
export class PlaybackClock {
  timeS = 0;
  rate = 30;
  playing = false;
  durationS = 0;
  private listeners = new Set<() => void>();

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  private emit(): void {
    this.listeners.forEach((l) => l());
  }

  tick(wallDtS: number): void {
    if (!this.playing) return;
    this.timeS = Math.min(this.durationS, this.timeS + wallDtS * this.rate);
    if (this.timeS >= this.durationS) this.playing = false;
    this.emit();
  }

  seek(t: number): void {
    this.timeS = Math.min(this.durationS, Math.max(0, t));
    this.emit();
  }

  setDuration(durationS: number): void {
    this.durationS = durationS;
    this.timeS = Math.min(this.timeS, durationS);
    this.emit();
  }
}

/** The scenario the simulation last ran successfully, and its result. The map draws this. */
export interface ActiveRun {
  scenario: ScenarioConfig;
  trajectory: Trajectory;
}

/** The Monte Carlo runner's state, kept with the scenario and settings it ran so any run can be replayed exactly. */
export interface McUi {
  status: 'idle' | 'running' | 'done' | 'error';
  done: number;
  total: number;
  result: McResult | null;
  error: string | null;
  spec: RedTeamSpec | null;
  base: ScenarioConfig | null;
}

/** Paths from several runs of a batch drawn together on the map, red where the outcome happened and green where it did not. */
export interface RunOverlay {
  label: string;
  working: boolean;
  hitRuns: number;
  missRuns: number;
  tracks: RunTrack[];
}

export interface Baseline {
  label: string;
  result: McResult;
}

const MC_IDLE: McUi = { status: 'idle', done: 0, total: 0, result: null, error: null, spec: null, base: null };

/** What the map is showing when it is replaying one run of a red-team batch instead of the scenario. */
export interface ReplayInfo {
  run: number;
  groupLabel: string;
  outcomeLabel: string | null;
  values: { label: string; value: number }[];
}

export interface ExerciseState {
  /** The scenario as edited. It may not run yet; see `errors`. */
  scenario: ScenarioConfig;
  errors: string[];
  active: ActiveRun;
  selectedId: string | null;
  view: ViewOptions;
  mapStyle: MapStyleId;
  follow: FollowMode;
  /** The next click on the map adds a waypoint to the selected unit. */
  placing: boolean;
  playing: boolean;
  rate: number;
  /** Full-screen presentation: the map covers the page and the panels are out of the way. */
  presenting: boolean;
  /** The red-team panel is open. */
  redTeamOpen: boolean;
  /** The storyboard panel is open. */
  storyOpen: boolean;
  /** The beat being edited, which the panel scrolls to. */
  focusedMomentId: string | null;
  /** The map is up and can be photographed for a storyboard moment. */
  canCapture: boolean;
  mc: McUi;
  /** A finished batch kept to compare the next one against. */
  baseline: Baseline | null;
  runOverlay: RunOverlay | null;
  replay: ReplayInfo | null;
  /** Bumps when a different scenario is loaded, so the map re-frames it. */
  scenarioRevision: number;
  /** Bumps when the user asks to see everything. */
  fitRevision: number;
  notice: string | null;
}

type Frame = (cb: (now: number) => void) => number;
const schedule: Frame = (cb) =>
  typeof requestAnimationFrame === 'function' ? requestAnimationFrame(cb) : (setTimeout(() => cb(Date.now()), 16) as unknown as number);
const unschedule = (h: number) => (typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame(h) : clearTimeout(h));

export class ExerciseController {
  readonly clock = new PlaybackClock();
  readonly state: Store<ExerciseState>;
  private raf = 0;
  private lastFrame = 0;
  private disposed = false;
  private mcStop = false;

  constructor(_host?: AppHost, initial: ScenarioConfig = PRESET_SCENARIOS[0]) {
    const scenario = clone(initial);
    this.state = new Store<ExerciseState>({
      scenario,
      errors: [],
      active: { scenario, trajectory: runScenario(scenario) },
      selectedId: null,
      view: DEFAULT_VIEW,
      mapStyle: 'standard',
      follow: 'off',
      placing: false,
      playing: false,
      rate: 30,
      presenting: false,
      redTeamOpen: false,
      storyOpen: false,
      focusedMomentId: null,
      canCapture: false,
      mc: MC_IDLE,
      baseline: null,
      runOverlay: null,
      replay: null,
      scenarioRevision: 0,
      fitRevision: 0,
      notice: null,
    });
    this.clock.setDuration(scenario.durationS);
  }

  /** Begin advancing the clock with the display. Safe to call once. */
  startLoop(): void {
    const frame = (now: number) => {
      if (this.disposed) return;
      const dt = this.lastFrame ? Math.min((now - this.lastFrame) / 1000, 0.25) : 0;
      this.lastFrame = now;
      this.clock.tick(dt);
      if (!this.clock.playing && this.state.get().playing) this.state.set({ playing: false });
      this.raf = schedule(frame);
    };
    this.raf = schedule(frame);
  }

  dispose(): void {
    this.disposed = true;
    this.mcStop = true;
    unschedule(this.raf);
  }

  // ---- playback ----

  play(): void {
    if (this.clock.timeS >= this.clock.durationS) this.clock.seek(0);
    this.clock.playing = true;
    this.lastFrame = 0;
    this.state.set({ playing: true });
  }

  pause(): void {
    this.clock.playing = false;
    this.state.set({ playing: false });
  }

  togglePlay(): void {
    if (this.clock.playing) this.pause();
    else this.play();
  }

  restart(): void {
    this.clock.seek(0);
  }

  setRate(rate: number): void {
    this.clock.rate = rate;
    this.state.set({ rate });
  }

  seek(t: number): void {
    this.clock.seek(t);
  }

  // ---- view ----

  setView(patch: Partial<ViewOptions>): void {
    this.state.set((s) => ({ view: { ...s.view, ...patch } }));
  }

  setMapStyle(mapStyle: MapStyleId): void {
    this.state.set({ mapStyle });
  }

  setPresenting(presenting: boolean): void {
    this.state.set({ presenting });
  }

  /** 'orbit' circles the selected ship, or the whole group when nothing is selected, so it needs no selection. */
  setFollow(follow: FollowMode): void {
    if ((follow === 'follow' || follow === 'chase') && !this.state.get().selectedId) {
      this.notify('Select a ship first, then follow it.');
      return;
    }
    this.state.set({ follow });
  }

  fitAll(): void {
    this.state.set((s) => ({ fitRevision: s.fitRevision + 1, follow: 'off' }));
  }

  select(id: string | null): void {
    this.state.set((s) => ({
      selectedId: id,
      placing: id ? s.placing : false,
      follow: id || s.follow === 'orbit' ? s.follow : 'off',
    }));
  }

  setPlacing(placing: boolean): void {
    if (placing && !this.state.get().selectedId) {
      this.notify('Select a ship, then click the map to add waypoints to its route.');
      return;
    }
    this.state.set({ placing });
  }

  notify(notice: string | null): void {
    this.state.set({ notice });
  }

  /** Every unit's state at the current instant of the run being shown. */
  currentStates(): UnitState[] {
    return statesAt(this.state.get().active.trajectory, this.clock.timeS);
  }

  // ---- scenario editing ----

  /** Replace the scenario. If it does not validate, keep it for editing but keep showing the last good run. */
  private apply(next: ScenarioConfig, loaded = false): void {
    const errors = validateScenario(next);
    if (errors.length) {
      this.state.set({ scenario: next, errors });
      return;
    }
    const active = { scenario: next, trajectory: runScenario(next) };
    this.clock.setDuration(next.durationS);
    this.state.set((s) => ({
      scenario: next,
      errors: [],
      active,
      selectedId: next.units.some((u) => u.id === s.selectedId) ? s.selectedId : null,
      scenarioRevision: loaded ? s.scenarioRevision + 1 : s.scenarioRevision,
      follow: loaded ? 'off' : s.follow,
      placing: loaded ? false : s.placing,
      replay: null,
      runOverlay: loaded ? null : s.runOverlay,
      mc: loaded && s.mc.status !== 'running' ? MC_IDLE : s.mc,
    }));
  }

  private edit(change: (draft: ScenarioConfig) => void): void {
    const draft = clone(this.state.get().scenario);
    change(draft);
    this.apply(draft);
  }

  loadScenario(scenario: ScenarioConfig): void {
    this.pause();
    this.clock.seek(0);
    const next = clone(scenario);
    if (this.state.get().redTeamOpen && !next.redTeam) next.redTeam = defaultRedTeam(next);
    this.apply(next, true);
  }

  loadPreset(id: string): void {
    const preset = id === 'blank' ? blankScenario() : PRESET_SCENARIOS.find((p) => p.id === id);
    if (preset) this.loadScenario(preset);
  }

  importJson(text: string): boolean {
    try {
      this.loadScenario(parseScenario(text));
      this.notify(null);
      return true;
    } catch (e) {
      this.notify(`Could not import: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    }
  }

  exportJson(): string {
    return exportScenario(this.state.get().scenario);
  }

  patchScenario(patch: Partial<Pick<ScenarioConfig, 'name' | 'description' | 'durationS' | 'lightPreset' | 'center' | 'seed' | 'detection' | 'seaState'>>): void {
    // Switches that are off are left out of the scenario rather than saved as false.
    this.edit((d) => {
      Object.assign(d, patch);
      if (!d.detection) delete d.detection;
      if (!d.seaState) delete d.seaState;
    });
  }

  patchEnvironment(patch: Partial<Environment>): void {
    this.edit((d) => Object.assign(d.environment, patch));
  }

  patchUnit(id: string, patch: Partial<UnitConfig>): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u) Object.assign(u, patch);
    });
  }

  /** Add a unit of any class with sensible defaults: ships and aircraft get a route, missiles a launcher and a target, mines a place. */
  addUnit(classId: ClassId = 'DDG'): void {
    const s = this.state.get().scenario;
    const cls = SHIP_CLASSES[classId];
    let n = s.units.length + 1;
    while (s.units.some((u) => u.id === `u${n}`)) n++;
    const slot = s.units.length % 6;
    const start = offsetM(s.center, 1500 * (slot - 2), -1500 * (s.units.length % 6));
    const base = { id: `u${n}`, name: `${cls.name.split(' (')[0]} ${n}`, classId, headingDeg: 90, start };
    let unit: UnitConfig;
    if (cls.domain === 'static') {
      unit = { ...base, side: 'RED', speedKt: 0, behavior: { type: 'hold' } };
    } else if (isMissile(cls)) {
      const platforms = s.units.filter((u) => isPlatform(SHIP_CLASSES[u.classId]));
      const launcher = platforms.find((u) => u.side === 'RED') ?? platforms[0];
      const target = platforms.find((u) => u.id !== launcher?.id && u.side !== launcher?.side) ?? platforms.find((u) => u.id !== launcher?.id);
      if (!launcher || !target) {
        this.notify('A missile needs a ship or aircraft to launch from and another to hit. Add those first.');
        return;
      }
      unit = { ...base, side: launcher.side, speedKt: 300, launch: { byId: launcher.id, atS: 60 }, behavior: { type: 'strike', targetId: target.id } };
    } else if (cls.domain === 'air') {
      unit = { ...base, side: 'BLUE', speedKt: cls.canHover ? 80 : 350, behavior: { type: 'route', waypoints: [destination(start, 90, 20000)] } };
    } else {
      unit = { ...base, side: 'BLUE', speedKt: 15, behavior: { type: 'route', waypoints: [destination(start, 90, 12000)] } };
    }
    this.edit((d) => d.units.push(unit));
    this.select(unit.id);
  }

  /** Fire several missiles at once: `count` units of `classId`, launched `gapS` apart from `firstAtS`. */
  addSalvo(launcherId: string, targetId: string, classId: ClassId, count: number, firstAtS: number, gapS: number): void {
    const cls = SHIP_CLASSES[classId];
    const s = this.state.get().scenario;
    const launcher = s.units.find((u) => u.id === launcherId);
    if (!launcher || !s.units.some((u) => u.id === targetId) || !isMissile(cls) || !(count >= 1)) {
      this.notify('A salvo needs a launcher, a target, a missile type and a count of at least 1.');
      return;
    }
    const n = Math.min(Math.round(count), 40);
    this.edit((d) => {
      let k = d.units.filter((u) => u.classId === classId).length;
      for (let i = 0; i < n; i++) {
        let id = `${classId.toLowerCase()}${++k}`;
        while (d.units.some((u) => u.id === id)) id = `${classId.toLowerCase()}${++k}`;
        d.units.push({
          id,
          name: `${cls.name.split(' (')[0]} ${k}`,
          classId,
          side: launcher.side,
          start: launcher.start,
          headingDeg: launcher.headingDeg,
          speedKt: 300,
          launch: { byId: launcherId, atS: Math.max(0, firstAtS + i * gapS) },
          behavior: { type: 'strike', targetId },
        });
      }
    });
  }

  removeUnit(id: string): void {
    this.edit((d) => {
      d.units = d.units.filter((u) => u.id !== id);
      for (const u of d.units) {
        const b = u.behavior;
        if ((b.type === 'escort' && b.leaderId === id) || (b.type === 'pursue' && b.targetId === id) || (b.type === 'strike' && b.targetId === id)) {
          u.behavior = { type: 'hold' };
        }
        // Things that were to be launched from a unit that no longer exists are left out rather than appearing from nowhere.
        if (u.launch?.byId === id) {
          delete u.launch;
          u.disabled = true;
        }
      }
      // Storyboard beats that hung on it stay, pinned to where it was, rather than vanishing with it.
      if (d.storyboard?.length) {
        d.storyboard = d.storyboard.map((m) => (m.unitId === id ? { ...m, unitId: undefined, at: m.at ?? d.center } : m));
      }
    });
  }

  patchLaunch(id: string, launch: { byId: string; atS: number } | null): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (!u) return;
      if (launch) u.launch = launch;
      else delete u.launch;
    });
  }

  /** Switch what a unit does, with sensible defaults for the new behavior. */
  setBehaviorType(id: string, type: Behavior['type']): void {
    const s = this.state.get().scenario;
    const unit = s.units.find((u) => u.id === id);
    if (!unit || unit.behavior.type === type) return;
    const others = s.units.filter((u) => u.id !== id);
    let behavior: Behavior;
    if (type === 'route') {
      behavior = { type: 'route', waypoints: [{ ...destination(unit.start, unit.headingDeg, 12000) }] };
    } else if (type === 'hold') {
      behavior = { type: 'hold' };
    } else if (type === 'loiter') {
      if (SHIP_CLASSES[unit.classId].domain !== 'air') {
        this.notify('Only aircraft can loiter.');
        return;
      }
      behavior = { type: 'loiter', center: unit.start, radiusM: 4000 };
    } else if (type === 'strike') {
      const target = others.find((o) => o.side !== unit.side && isPlatform(SHIP_CLASSES[o.classId])) ?? others.find((o) => isPlatform(SHIP_CLASSES[o.classId]));
      if (!isMissile(SHIP_CLASSES[unit.classId]) || !target) {
        this.notify(!isMissile(SHIP_CLASSES[unit.classId]) ? 'Only missiles can strike.' : 'Add a ship or aircraft to hit first.');
        return;
      }
      behavior = { type: 'strike', targetId: target.id };
    } else {
      const other = type === 'pursue' ? (others.find((o) => o.side !== unit.side) ?? others[0]) : others[0];
      if (!other) {
        this.notify(`Add another unit first: ${type === 'escort' ? 'there is nobody to escort' : 'there is nothing to pursue'}.`);
        return;
      }
      behavior =
        type === 'escort'
          ? { type: 'escort', leaderId: other.id, aheadM: 0, abeamM: 2000 }
          : { type: 'pursue', targetId: other.id, standoffM: 3000 };
    }
    this.patchUnit(id, { behavior });
  }

  patchBehavior(id: string, patch: Partial<Behavior>): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u) u.behavior = { ...u.behavior, ...patch } as Behavior;
    });
  }

  addWaypoint(id: string, at: LonLat): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (!u) return;
      if (u.behavior.type === 'route') u.behavior.waypoints.push({ ...at });
      else u.behavior = { type: 'route', waypoints: [{ ...at }] };
    });
  }

  patchWaypoint(id: string, index: number, patch: Partial<Waypoint>): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u?.behavior.type !== 'route' || !u.behavior.waypoints[index]) return;
      const w = u.behavior.waypoints[index];
      Object.assign(w, patch);
      if (w.speedKt === undefined) delete w.speedKt;
      if (w.altitudeM === undefined) delete w.altitudeM;
    });
  }

  /** Add a waypoint so that it becomes number `index` (counting from 0) of the route. */
  insertWaypoint(id: string, index: number, at: LonLat): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u?.behavior.type === 'route') u.behavior.waypoints.splice(Math.max(0, Math.min(index, u.behavior.waypoints.length)), 0, { lon: at.lon, lat: at.lat });
    });
  }

  removeWaypoint(id: string, index: number): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u?.behavior.type === 'route') u.behavior.waypoints.splice(index, 1);
    });
  }

  // ---- storyboard ----

  /** Takes a picture of the map as it looks now. Set by the map view when it starts; absent until then. */
  private capture: ((maxWidth?: number, quality?: number) => Promise<string>) | null = null;

  setCapture(fn: ((maxWidth?: number, quality?: number) => Promise<string>) | null): void {
    this.capture = fn;
    if (!this.disposed) this.state.set({ canCapture: fn !== null });
  }

  toggleStoryboard(open?: boolean): void {
    this.state.set((s) => ({ storyOpen: open ?? !s.storyOpen }));
  }

  storyboard(): StoryMoment[] {
    return this.state.get().scenario.storyboard ?? [];
  }

  storyboardProblems(): string[] {
    const s = this.state.get().scenario;
    return validateStoryboard(s, s.storyboard ?? []);
  }

  /**
   * Change the storyboard. Pictures and captions do not change how the run goes, so this never re-runs the simulation; it
   * puts the new beats on both the scenario being edited and the run on screen.
   */
  private editStory(change: (moments: StoryMoment[]) => StoryMoment[]): void {
    this.state.set((s) => {
      const moments = inOrder(change(s.scenario.storyboard ?? []));
      return {
        scenario: { ...s.scenario, storyboard: moments },
        active: { ...s.active, scenario: { ...s.active.scenario, storyboard: moments } },
      };
    });
  }

  setStoryboard(moments: StoryMoment[]): void {
    this.editStory(() => moments);
  }

  /** Build a storyboard from what happens in the run on screen, with a stock picture on each beat. */
  generateStoryboard(options: AutoOptions = {}): void {
    const { active } = this.state.get();
    const moments = autoStoryboard(active.scenario, active.trajectory, {
      picture: (event, unitId) => {
        const unit = unitId ? active.scenario.units.find((u) => u.id === unitId) : undefined;
        // The opening beat matches no event and no unit, so it gets the general one.
        return pickStock(event, unit?.classId)?.url ?? stock.formation;
      },
      ...options,
    });
    this.editStory(() => moments);
    this.state.set({ focusedMomentId: moments[0]?.id ?? null });
  }

  /** Add a beat at the moment on the clock, on the selected unit. */
  addMoment(patch: Partial<StoryMoment> = {}): string {
    const s = this.state.get();
    const id = patch.id ?? nextMomentId(s.scenario.storyboard ?? []);
    const unitId = patch.unitId ?? s.selectedId ?? undefined;
    const unit = unitId ? s.scenario.units.find((u) => u.id === unitId) : undefined;
    const moment: StoryMoment = {
      id,
      unitId: unit?.id,
      at: unit ? undefined : s.scenario.center,
      atS: Math.round(this.clock.timeS),
      holdS: defaultHoldS(s.scenario.durationS),
      title: unit ? unit.name : 'New moment',
      ...patch,
    };
    this.editStory((moments) => [...moments, moment]);
    this.state.set({ focusedMomentId: id });
    return id;
  }

  patchMoment(id: string, patch: Partial<StoryMoment>): void {
    this.editStory((moments) =>
      moments.map((m) => {
        if (m.id !== id) return m;
        const next = { ...m, ...patch };
        // A beat hangs on a unit or on a spot, not both.
        if (next.unitId) delete next.at;
        else if (!next.at) next.at = this.state.get().scenario.center;
        if (!next.caption) delete next.caption;
        if (!next.image) delete next.image;
        return next;
      }),
    );
  }

  removeMoment(id: string): void {
    this.editStory((moments) => moments.filter((m) => m.id !== id));
    this.state.set((s) => ({ focusedMomentId: s.focusedMomentId === id ? null : s.focusedMomentId }));
  }

  /** Open a beat in the panel and wind the clock to it, so clicking a bubble shows what it is about. */
  focusMoment(id: string): void {
    const m = this.storyboard().find((x) => x.id === id);
    if (!m) return;
    this.state.set({ storyOpen: true, focusedMomentId: id, selectedId: m.unitId ?? null });
    this.clock.seek(m.atS);
  }

  /** Take a picture of the map as it looks now and put it on a beat. Returns false if the map cannot be captured. */
  async captureInto(id: string): Promise<boolean> {
    if (!this.capture) return false;
    const image = await this.capture();
    if (this.disposed) return false;
    this.patchMoment(id, { image });
    return true;
  }

  clearStoryboardImages(): void {
    this.editStory((moments) =>
      moments.map((m) => {
        if (!m.image) return m;
        const next = { ...m };
        delete next.image;
        return next;
      }),
    );
  }

  // ---- red team ----

  toggleRedTeam(open?: boolean): void {
    const opening = open ?? !this.state.get().redTeamOpen;
    // Opening it for the first time gives the scenario a suggested setup to start from.
    if (opening && !this.state.get().scenario.redTeam) this.redTeamSpec();
    this.state.set({ redTeamOpen: opening });
  }

  /** The scenario's red-team settings, or sensible ones for it if it has none yet. Saves them with the scenario. */
  redTeamSpec(): RedTeamSpec {
    const s = this.state.get().scenario;
    if (s.redTeam) return s.redTeam;
    const spec = defaultRedTeam(s);
    this.setRedTeam(spec);
    return spec;
  }

  /** Change the red-team settings. This does not re-run the scenario you are watching. */
  setRedTeam(spec: RedTeamSpec): void {
    this.state.set((s) => ({ scenario: { ...s.scenario, redTeam: spec } }));
  }

  /** Problems with the current red-team settings, by name, for showing next to them. */
  redTeamProblems(): string[] {
    const s = this.state.get().scenario;
    return s.redTeam ? validateRedTeam(s, s.redTeam) : [];
  }

  async runRedTeam(): Promise<void> {
    if (this.state.get().mc.status === 'running') return;
    const base = clone(this.state.get().scenario);
    const spec = clone(base.redTeam ?? this.redTeamSpec());
    this.mcStop = false;
    this.state.set({ mc: { ...MC_IDLE, status: 'running', spec, base } });
    try {
      const result = await runMonteCarlo(base, spec, {
        onProgress: (done, total) => this.state.set((s) => ({ mc: { ...s.mc, done, total } })),
        shouldStop: () => this.mcStop,
      });
      if (!this.disposed) this.state.set((s) => ({ mc: { ...s.mc, status: 'done', result, done: result.totalRuns } }));
    } catch (e) {
      if (!this.disposed) this.state.set((s) => ({ mc: { ...s.mc, status: 'error', error: e instanceof Error ? e.message : String(e) } }));
    }
  }

  stopRedTeam(): void {
    this.mcStop = true;
  }

  /** Keep the finished batch to compare the next one against: change the scenario or a setting, run again, and see what moved. */
  pinBaseline(): void {
    const { mc } = this.state.get();
    if (!mc.result || !mc.base) return;
    this.state.set({ baseline: { label: `${mc.base.name}, ${mc.result.totalRuns.toLocaleString('en-US')} runs`, result: mc.result } });
  }

  clearBaseline(): void {
    this.state.set({ baseline: null });
  }

  /** Show one run of the finished batch on the map: the same random draws, the same chance rolls. */
  replayRun(groupIndex: number, run: number, outcomeLabel: string | null = null): void {
    const { mc } = this.state.get();
    if (!mc.result || !mc.spec || !mc.base) return;
    const group = mc.result.groups[groupIndex];
    if (!group) return;
    const prepared = prepareRun(mc.base, mc.spec, run, group.sweepValue);
    const trajectory = runScenario(prepared.scenario, { seed: prepared.seed });
    this.pause();
    this.clock.setDuration(prepared.scenario.durationS);
    this.clock.seek(0);
    this.state.set((s) => ({
      active: { scenario: prepared.scenario, trajectory },
      selectedId: prepared.scenario.units.some((u) => u.id === s.selectedId) ? s.selectedId : null,
      follow: 'off',
      placing: false,
      scenarioRevision: s.scenarioRevision + 1,
      replay: {
        run: run + 1,
        groupLabel: group.label,
        outcomeLabel,
        values: mc.spec!.perturbations
          .filter((p) => Number.isFinite(prepared.values[p.id]))
          .map((p) => ({ label: p.label ?? p.id, value: prepared.values[p.id] })),
      },
    }));
  }

  private overlayToken = 0;

  /**
   * Draw the paths of a few runs where the outcome happened and a few where it did not, on the map together, to see what the
   * difference looks like. Each run is the same one a replay would show.
   */
  async showRunOverlay(groupIndex: number, outcomeId: string, label: string, perSide = 6): Promise<void> {
    const { mc } = this.state.get();
    const group = mc.result?.groups[groupIndex];
    if (!group || !mc.spec || !mc.base) return;
    const token = ++this.overlayToken;
    const picks = [
      ...(group.hitRuns[outcomeId] ?? []).slice(0, perSide).map((k) => ({ k, hit: true })),
      ...(group.missRuns[outcomeId] ?? []).slice(0, perSide).map((k) => ({ k, hit: false })),
    ];
    const counts = { hitRuns: picks.filter((p) => p.hit).length, missRuns: picks.filter((p) => !p.hit).length };
    this.state.set({ runOverlay: { label, working: true, ...counts, tracks: [] } });
    const tracks: RunTrack[] = [];
    for (const { k, hit } of picks) {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      if (token !== this.overlayToken || this.disposed) return;
      const run = prepareRun(mc.base, mc.spec, k, group.sweepValue);
      tracks.push(...runTracks(run.scenario, runScenario(run.scenario, { seed: run.seed }), hit));
    }
    this.state.set({ runOverlay: { label, working: false, ...counts, tracks } });
  }

  clearRunOverlay(): void {
    this.overlayToken++;
    this.state.set({ runOverlay: null });
  }

  /** Go back from a replayed run to the scenario as edited. */
  exitReplay(): void {
    const { scenario } = this.state.get();
    if (validateScenario(scenario).length) return;
    this.pause();
    this.clock.setDuration(scenario.durationS);
    this.clock.seek(0);
    this.state.set((s) => ({
      active: { scenario, trajectory: runScenario(scenario) },
      replay: null,
      scenarioRevision: s.scenarioRevision + 1,
    }));
  }
}
