import { Store } from '../../lib/store';
import type { AppHost } from '../../scene/app';
import { destination, offsetM } from './geo';
import type { MapStyleId } from './mapStyles';
import { DEFAULT_VIEW } from './scene';
import type { ViewOptions } from './scene';
import { PRESET_SCENARIOS, blankScenario, clone } from './scenarios';
import { exportScenario, parseScenario } from './scenarioJson';
import { SHIP_CLASSES } from './ships';
import { runScenario, statesAt, validateScenario } from './sim';
import type { Trajectory } from './sim';
import type { Behavior, Environment, LonLat, ScenarioConfig, UnitConfig, UnitState, Waypoint } from './types';

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
    this.apply(clone(scenario), true);
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

  patchScenario(patch: Partial<Pick<ScenarioConfig, 'name' | 'description' | 'durationS' | 'lightPreset' | 'center'>>): void {
    this.edit((d) => Object.assign(d, patch));
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

  addUnit(): void {
    const s = this.state.get().scenario;
    let n = s.units.length + 1;
    while (s.units.some((u) => u.id === `u${n}`)) n++;
    const start = offsetM(s.center, 0, -1500 * (s.units.length % 6));
    const unit: UnitConfig = {
      id: `u${n}`,
      name: `${SHIP_CLASSES.DDG.name.split(' (')[0]} ${n}`,
      classId: 'DDG',
      side: 'BLUE',
      start,
      headingDeg: 90,
      speedKt: 15,
      behavior: { type: 'route', waypoints: [destination(start, 90, 12000)] },
    };
    this.edit((d) => d.units.push(unit));
    this.select(unit.id);
  }

  removeUnit(id: string): void {
    this.edit((d) => {
      d.units = d.units.filter((u) => u.id !== id);
      for (const u of d.units) {
        const b = u.behavior;
        if ((b.type === 'escort' && b.leaderId === id) || (b.type === 'pursue' && b.targetId === id)) {
          u.behavior = { type: 'hold' };
        }
      }
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
    });
  }

  removeWaypoint(id: string, index: number): void {
    this.edit((d) => {
      const u = d.units.find((x) => x.id === id);
      if (u?.behavior.type === 'route') u.behavior.waypoints.splice(index, 1);
    });
  }
}
