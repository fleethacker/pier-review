import { bearingTo, distanceM, formatClock, mToNm } from './geo';
import { SHIP_CLASSES } from './ships';
import { detectionRangeM, seaStateFromWind, statesAt, unitStateAt } from './sim';
import type { EventType, SimEvent, Trajectory } from './sim';
import { eventFocus, eventText } from './status';
import type { ScenarioConfig, UnitConfig, UnitState } from './types';

/**
 * The data catalog: turns a finished run into the raw-looking records a collection source would have produced, so a
 * click on an event can show "here is the track/report/message that is this event" instead of only the event itself.
 * Nothing here is a real sensor — every number is read off the simulation's own state at the time in question, and
 * each feed says as much in `derivedFrom`. No React, no DOM, no I/O.
 */

export type Discipline = 'RADAR' | 'ACOUSTIC' | 'SIGINT' | 'COMMS' | 'IMINT' | 'SYSTEM';
export type FeedId = 'surface-radar' | 'airborne-radar' | 'acoustic' | 'elint' | 'comms' | 'fmv' | 'overhead' | 'weapons';

export interface FeedDef {
  id: FeedId;
  label: string;
  discipline: Discipline;
  /** One line: what it is. */
  blurb: string;
  /** Exactly what in the run it is derived from. */
  derivedFrom: string;
}

/** How far a UAV or helicopter's camera is taken to reach, meters. Used only to decide which events it would have framed. */
const FMV_FOOTPRINT_M = 25_000;

/** How many overhead passes are simulated across a run, spread evenly from start to finish. The cadence between passes is this run's length divided by one less than this count. */
export const OVERHEAD_PASSES = 5;

export const FEEDS: FeedDef[] = [
  { id: 'surface-radar', label: 'Surface search radar', discipline: 'RADAR', blurb: 'Surface-ship radar tracks of nearby contacts.', derivedFrom: "'detected' events where the detecting unit is a surface ship; range, bearing and the target's course and speed are read off both units' real state at that instant." },
  { id: 'airborne-radar', label: 'Airborne radar', discipline: 'RADAR', blurb: 'Radar tracks from aircraft: AEW, fighters, helicopters, UAVs.', derivedFrom: "'detected' events where the detecting unit's class domain is air; same geometry as surface radar, read off the aircraft's own state." },
  { id: 'acoustic', label: 'Acoustic', discipline: 'ACOUSTIC', blurb: 'Sonar bearing-and-range reports on submarines and torpedoes.', derivedFrom: "'detected' events where either side of the pair is a submarine or torpedo (class domain 'sub'); bearing, range and the target's speed from the run's own geometry." },
  { id: 'elint', label: 'ELINT', discipline: 'SIGINT', blurb: 'Emitter report from a platform radiating to launch a weapon.', derivedFrom: "'launch' events: the launcher's position and class, the weapon class launched, and the bearing from the launcher to the weapon's own target." },
  { id: 'comms', label: 'Tactical comms', discipline: 'COMMS', blurb: 'Traffic reporting holds, aborted launches, hits, losses and mine strikes.', derivedFrom: "'held', 'aborted', 'hit', 'destroyed' and 'mine' events, worded with the same text the rest of the app uses to describe them (status.ts eventText)." },
  { id: 'fmv', label: 'Full-motion video', discipline: 'IMINT', blurb: 'Frame metadata, no imagery, from a UAV or helicopter overflying an event.', derivedFrom: "events that fall within 25 km of a UAV's or helicopter's own position at that instant; slant range, ground range and altitude computed from the aircraft's state." },
  { id: 'overhead', label: 'Overhead imagery', discipline: 'IMINT', blurb: 'Standing satellite-style passes over the whole area, no imagery, metadata only.', derivedFrom: `${OVERHEAD_PASSES} passes spread evenly across the run; each pass lists every unit still active and its position from the trajectory at that instant.` },
  { id: 'weapons', label: 'Weapons', discipline: 'SYSTEM', blurb: 'Fire-control engagement log of intercepts and misses.', derivedFrom: "'intercept' and 'miss' events: the firing or launching unit, the weapon, the target when there is one, and the outcome." },
];

export interface DataRecord {
  id: string;
  feed: FeedId;
  /** Seconds into the run. */
  tS: number;
  /** Index into trajectory.events when this record is the provenance of an event; undefined for standing collection (imagery passes). */
  eventIndex?: number;
  /** The collecting unit, when one can be named from the run. */
  byUnitId?: string;
  /** Units the record is about. */
  aboutUnitIds: string[];
  title: string;
  /** Field/value pairs shown in a readout. Values already formatted. */
  fields: [string, string][];
  /** The record as a machine or signal operator would see it: JSON for machine feeds, a formatted message for comms. */
  raw: string;
}

const round = (v: number, d: number): number => Math.round(v * 10 ** d) / 10 ** d;

const COMMS_LABEL: Partial<Record<EventType, string>> = {
  aborted: 'Launch aborted',
  hit: 'Weapon impact',
  destroyed: 'Unit lost',
  mine: 'Mine strike',
  held: 'Shot held',
};

/**
 * Everything a run produced, reshaped into the records its collection sources would have carried. Sorted by time so a
 * caller can page through the picture as it built up.
 */
export function deriveRecords(scenario: ScenarioConfig, trajectory: Trajectory): DataRecord[] {
  const cfgById = new Map(scenario.units.map((u): [string, UnitConfig] => [u.id, u]));
  const idxById = new Map(trajectory.unitIds.map((id, i): [string, number] => [id, i]));
  const name = (id: string) => cfgById.get(id)?.name ?? id;
  const stateAt = (id: string, tS: number): UnitState | undefined => {
    const i = idxById.get(id);
    return i === undefined ? undefined : unitStateAt(trajectory, i, tS);
  };
  const seaState = scenario.seaState ? seaStateFromWind(scenario.environment.windKt) : 0;

  const counters: Partial<Record<FeedId, number>> = {};
  const records: DataRecord[] = [];
  const add = (feed: FeedId, tS: number, eventIndex: number | undefined, rest: Omit<DataRecord, 'id' | 'feed' | 'tS' | 'eventIndex'>) => {
    const n = counters[feed] ?? 0;
    counters[feed] = n + 1;
    records.push({ id: `${feed}-${n}`, feed, tS, eventIndex, ...rest });
  };

  trajectory.events.forEach((e, i) => {
    if (e.type === 'detected') addDetection(e, i);
    else if (e.type === 'launch') addLaunch(e, i);
    else if (e.type === 'intercept' || e.type === 'miss') addEngagement(e, i);
    else if (COMMS_LABEL[e.type]) addComms(e, i);
  });
  addFmv();
  addOverhead();

  records.sort((a, b) => a.tS - b.tS || a.id.localeCompare(b.id));
  return records;

  function addDetection(e: SimEvent, i: number) {
    const target = cfgById.get(e.unitId);
    const detector = e.otherId ? cfgById.get(e.otherId) : undefined;
    const targetState = stateAt(e.unitId, e.tS);
    const detectorState = e.otherId ? stateAt(e.otherId, e.tS) : undefined;
    if (!target || !detector || !targetState || !detectorState || !e.otherId) return;
    const targetCls = SHIP_CLASSES[target.classId];
    const detectorCls = SHIP_CLASSES[detector.classId];
    const rangeM = distanceM(detectorState, targetState);
    const bearingDeg = bearingTo(detectorState, targetState);

    if (targetCls.domain === 'sub' || detectorCls.domain === 'sub') {
      add('acoustic', e.tS, i, {
        byUnitId: detector.id,
        aboutUnitIds: [target.id],
        title: `${name(detector.id)} — sonar contact`,
        fields: [
          ['Bearing', `${round(bearingDeg, 0)}°T`],
          ['Range', `${round(mToNm(rangeM), 1)} nm`],
          ['Target speed', `${round(targetState.speedKt, 1)} kt`],
          ['Method', 'The simulation models detection as deterministic once in range: this is a reported contact, not a probabilistic one.'],
        ],
        raw: JSON.stringify({ kind: 'bearing-line', sensor: detector.id, contact: target.id, bearingDeg: round(bearingDeg, 1), rangeNm: round(mToNm(rangeM), 2), targetSpeedKt: round(targetState.speedKt, 1), tS: e.tS, source: 'synthesised from simulation state' }),
      });
      return;
    }

    const feed: FeedId | undefined = detectorCls.domain === 'air' ? 'airborne-radar' : detectorCls.domain === 'surface' ? 'surface-radar' : undefined;
    if (!feed) return;
    const ownRangeM = detectionRangeM(detector, detectorState.altM, target, targetState.altM, targetState.speedKt, seaState);
    add(feed, e.tS, i, {
      byUnitId: detector.id,
      aboutUnitIds: [target.id],
      title: `${name(detector.id)} — radar contact`,
      fields: [
        ['Bearing', `${round(bearingDeg, 0)}°T`],
        ['Range', `${round(mToNm(rangeM), 1)} nm`],
        ['Course over ground', `${round(targetState.cogDeg, 0)}°T`],
        ['Speed over ground', `${round(targetState.sogKt, 1)} kt`],
        ['Sensor max range', `${round(mToNm(ownRangeM), 1)} nm`],
      ],
      raw: JSON.stringify({ kind: 'track', sensor: detector.id, contact: target.id, bearingDeg: round(bearingDeg, 1), rangeM: round(rangeM, 0), cogDeg: round(targetState.cogDeg, 1), sogKt: round(targetState.sogKt, 1), sensorRangeM: round(ownRangeM, 0), tS: e.tS, source: 'synthesised from simulation state' }),
    });
  }

  function addLaunch(e: SimEvent, i: number) {
    const launched = cfgById.get(e.unitId);
    const launcher = e.otherId ? cfgById.get(e.otherId) : undefined;
    if (!launched || !launcher) return;
    const launcherState = stateAt(launcher.id, e.tS);
    let bearingDeg: number | undefined;
    if (launched.behavior.type === 'strike' && launcherState) {
      const targetState = stateAt(launched.behavior.targetId, e.tS);
      if (targetState) bearingDeg = bearingTo(launcherState, targetState);
    }
    add('elint', e.tS, i, {
      byUnitId: undefined,
      aboutUnitIds: [launcher.id, launched.id],
      title: `${name(launcher.id)} — emission detected`,
      fields: [
        ['Emitter platform', name(launcher.id)],
        ['Weapon class launched', SHIP_CLASSES[launched.classId].name],
        ...(bearingDeg !== undefined ? ([['Bearing to target', `${round(bearingDeg, 0)}°T`]] as [string, string][]) : []),
        ['Time', `T+${formatClock(e.tS)}`],
      ],
      raw: JSON.stringify({ kind: 'emitter', platform: launcher.id, weaponClass: launched.classId, bearingToTargetDeg: bearingDeg !== undefined ? round(bearingDeg, 1) : null, tS: e.tS, source: 'synthesised from simulation state' }),
    });
  }

  function addEngagement(e: SimEvent, i: number) {
    const firedBy = e.type === 'intercept' ? (e.otherId ?? e.unitId) : (cfgById.get(e.unitId)?.launch?.byId ?? e.unitId);
    const outcome = e.type === 'intercept' ? 'Intercepted' : `Missed${e.detail ? ` — ${e.detail}` : ''}`;
    const about = [e.unitId, e.otherId].filter((x): x is string => !!x);
    add('weapons', e.tS, i, {
      byUnitId: firedBy,
      aboutUnitIds: about,
      title: `${name(firedBy)} — ${outcome}`,
      fields: [
        ['Firing/launching unit', name(firedBy)],
        ['Weapon', name(e.unitId)],
        ...(e.otherId ? ([['Target', name(e.otherId)]] as [string, string][]) : []),
        ['Outcome', outcome],
        ['Time', `T+${formatClock(e.tS)}`],
      ],
      raw: JSON.stringify({ kind: 'engagement', by: firedBy, weapon: e.unitId, target: e.otherId ?? null, outcome, tS: e.tS, source: 'synthesised from simulation state' }),
    });
  }

  function addComms(e: SimEvent, i: number) {
    const originator = eventFocus(e, scenario.units) ?? e.unitId;
    const about = [e.unitId, e.otherId].filter((x): x is string => !!x);
    const body = eventText(e, name);
    const dtg = `T+${formatClock(e.tS)}`;
    add('comms', e.tS, i, {
      byUnitId: originator,
      aboutUnitIds: about,
      title: `${name(originator)} — ${COMMS_LABEL[e.type] ?? e.type}`,
      fields: [
        ['Originator', name(originator)],
        ['Time group', dtg],
        ['Message', body],
      ],
      raw: `FM ${name(originator).toUpperCase()}\nDTG ${dtg}\n${body}`,
    });
  }

  function addFmv() {
    const aircraft = scenario.units.filter((u) => u.classId === 'UAV' || u.classId === 'HELO');
    if (aircraft.length === 0) return;
    for (const ac of aircraft) {
      const acIdx = idxById.get(ac.id);
      if (acIdx === undefined) continue;
      trajectory.events.forEach((e, i) => {
        const acState = unitStateAt(trajectory, acIdx, e.tS);
        if (!acState.active) return;
        const groundRangeM = distanceM(acState, e);
        if (groundRangeM > FMV_FOOTPRINT_M) return;
        const slantRangeM = Math.hypot(groundRangeM, acState.altM);
        const states = statesAt(trajectory, e.tS);
        const inView = trajectory.unitIds.filter((id, u) => id !== ac.id && states[u].active && distanceM(acState, states[u]) <= FMV_FOOTPRINT_M);
        add('fmv', e.tS, i, {
          byUnitId: ac.id,
          aboutUnitIds: inView,
          title: `${name(ac.id)} — frame at T+${formatClock(e.tS)}`,
          fields: [
            ['Platform', name(ac.id)],
            ['Slant range', `${round(mToNm(slantRangeM), 2)} nm`],
            ['Ground range', `${round(mToNm(groundRangeM), 2)} nm`],
            ['Altitude', `${round(acState.altM, 0)} m`],
            ['Units in frame', inView.length ? inView.map(name).join(', ') : 'none'],
            ['Imagery', 'No image was captured. This is simulated frame metadata only.'],
          ],
          raw: JSON.stringify({ kind: 'fmv-frame', platform: ac.id, slantRangeM: round(slantRangeM, 0), groundRangeM: round(groundRangeM, 0), altitudeM: round(acState.altM, 0), unitsInFrame: inView, tS: e.tS, source: 'synthesised from simulation state, no imagery exists' }),
        });
      });
    }
  }

  function addOverhead() {
    const cadenceS = scenario.durationS / (OVERHEAD_PASSES - 1);
    for (let p = 0; p < OVERHEAD_PASSES; p++) {
      const tS = Math.round(p * cadenceS);
      const states = statesAt(trajectory, tS);
      const inView = trajectory.unitIds
        .map((id, u) => ({ id, st: states[u] }))
        .filter(({ st }) => st.active && st.hp > 0);
      add('overhead', tS, undefined, {
        byUnitId: undefined,
        aboutUnitIds: inView.map((v) => v.id),
        title: `Overhead pass ${p + 1} of ${OVERHEAD_PASSES} — T+${formatClock(tS)}`,
        fields: [
          ['Pass', `${p + 1} of ${OVERHEAD_PASSES}`],
          ['Units in view', `${inView.length}`],
          ['Imagery', 'No image was captured. This is simulated pass metadata only.'],
        ],
        raw: JSON.stringify({ kind: 'overhead-pass', pass: p + 1, tS, units: inView.map(({ id, st }) => ({ id, lat: round(st.lat, 4), lon: round(st.lon, 4) })), source: 'synthesised from simulation state, no imagery exists' }),
      });
    }
  }
}

/** The records that document one event: what you would see if you clicked it in the catalog. */
export function recordsForEvent(records: DataRecord[], eventIndex: number): DataRecord[] {
  return records.filter((r) => r.eventIndex === eventIndex);
}

export interface CatalogEntry {
  feed: FeedDef;
  records: number;
  firstS: number | null;
  lastS: number | null;
  platforms: string[];
}

/** One line per feed, in FEEDS order, so a feed with nothing in it still shows up as a source that exists but has no traffic. */
export function catalogOf(scenario: ScenarioConfig, records: DataRecord[]): CatalogEntry[] {
  const label = (id: string) => scenario.units.find((u) => u.id === id)?.name ?? id;
  return FEEDS.map((feed): CatalogEntry => {
    let firstS: number | null = null;
    let lastS: number | null = null;
    const platformIds = new Set<string>();
    let count = 0;
    for (const r of records) {
      if (r.feed !== feed.id) continue;
      count++;
      firstS = firstS === null ? r.tS : Math.min(firstS, r.tS);
      lastS = lastS === null ? r.tS : Math.max(lastS, r.tS);
      if (r.byUnitId) platformIds.add(r.byUnitId);
      for (const id of r.aboutUnitIds) platformIds.add(id);
    }
    return { feed, records: count, firstS, lastS, platforms: [...platformIds].map(label).sort() };
  });
}
