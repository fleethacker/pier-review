import { describe, expect, it } from 'vitest';
import { catalogOf, deriveRecords, FEEDS, OVERHEAD_PASSES, recordsForEvent } from './datasources';
import { destination, distanceM } from './geo';
import { PRESET_SCENARIOS } from './scenarios';
import { runScenario, unitStateAt } from './sim';
import type { Environment, ScenarioConfig, UnitConfig } from './types';

const C = { lon: -62, lat: 33 };
const still: Environment = { windFromDeg: 0, windKt: 0, currentToDeg: 0, currentKt: 0 };
const unit = (patch: Partial<UnitConfig> & Pick<UnitConfig, 'id'>): UnitConfig => ({
  name: patch.id,
  classId: 'DDG',
  side: 'BLUE',
  start: C,
  headingDeg: 90,
  speedKt: 0,
  behavior: { type: 'hold' },
  magazine: 0,
  ...patch,
});
const scenario = (units: UnitConfig[], patch: Partial<ScenarioConfig> = {}): ScenarioConfig => ({
  id: 't',
  name: 'Test exercise',
  description: 'A test run.',
  center: C,
  durationS: 600,
  lightPreset: 'day',
  environment: still,
  units,
  ...patch,
});

// 'joint-task-force' is the richest preset: sensors, seaState and over a hundred units, so it exercises nearly every
// kind of event the run can produce (everything but an aborted launch, which nothing in it triggers).
const jtf = PRESET_SCENARIOS.find((p) => p.id === 'joint-task-force')!;
const jtfTraj = runScenario(jtf);
const jtfRecords = deriveRecords(jtf, jtfTraj);

// A small, fast preset with a helicopter escorting the carrier, used where a quick run is enough.
const salvo = PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
const salvoTraj = runScenario(salvo);
const salvoRecords = deriveRecords(salvo, salvoTraj);

describe('deriving records from a run', () => {
  it('produces records for more than one preset, sorted by time', () => {
    for (const records of [jtfRecords, salvoRecords]) {
      expect(records.length).toBeGreaterThan(0);
      const times = records.map((r) => r.tS);
      expect(times).toEqual([...times].sort((a, b) => a - b));
    }
  });

  it('gives every record a stable, unique id of the form feed-index', () => {
    const ids = jtfRecords.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const r of jtfRecords) expect(r.id).toMatch(new RegExp(`^${r.feed}-\\d+$`));
  });

  it('is deterministic: the same scenario and trajectory give the same records twice', () => {
    expect(deriveRecords(jtf, jtfTraj)).toEqual(deriveRecords(jtf, jtfTraj));
    expect(deriveRecords(salvo, salvoTraj)).toEqual(deriveRecords(salvo, salvoTraj));
  });

  it('points a record at every kind of event the run actually produced', () => {
    const seen = new Set(jtfTraj.events.map((e) => e.type));
    // A sanity check on the fixture itself: this preset should be exercising plenty of variety.
    expect(seen.size).toBeGreaterThanOrEqual(7);
    const covered = new Set(jtfRecords.filter((r) => r.eventIndex !== undefined).map((r) => jtfTraj.events[r.eventIndex!].type));
    for (const type of seen) expect(covered.has(type), `no record has an eventIndex pointing at a '${type}' event`).toBe(true);
  });

  it('covers an aborted launch too, from a scenario built to produce one', () => {
    const s = scenario([
      unit({ id: 'shooter', side: 'RED', start: destination(C, 0, 20_000) }),
      unit({ id: 'victim', hp: 50 }),
      unit({ id: 'killer', classId: 'ASM', side: 'RED', speedKt: 300, launch: { byId: 'shooter', atS: 0 }, behavior: { type: 'strike', targetId: 'victim' }, pHit: 1, damage: 200 }),
      unit({ id: 'late', classId: 'ASM', side: 'BLUE', speedKt: 300, launch: { byId: 'victim', atS: 300 }, behavior: { type: 'strike', targetId: 'shooter' } }),
    ]);
    const t = runScenario(s);
    const abortedIndex = t.events.findIndex((e) => e.type === 'aborted');
    expect(abortedIndex).toBeGreaterThanOrEqual(0);
    const records = deriveRecords(s, t);
    const aborted = recordsForEvent(records, abortedIndex);
    expect(aborted.length).toBeGreaterThan(0);
    expect(aborted.every((r) => r.feed === 'comms')).toBe(true);
  });

  it('recordsForEvent returns only that event\'s records, and nothing for an event with none', () => {
    const withIndex = jtfRecords.find((r) => r.eventIndex !== undefined)!;
    const picked = recordsForEvent(jtfRecords, withIndex.eventIndex!);
    expect(picked.length).toBeGreaterThan(0);
    expect(picked.every((r) => r.eventIndex === withIndex.eventIndex)).toBe(true);
    expect(picked).toEqual(jtfRecords.filter((r) => r.eventIndex === withIndex.eventIndex));
    // An index no event has: nothing claims it.
    expect(recordsForEvent(jtfRecords, jtfTraj.events.length + 1000)).toEqual([]);
  });

  it('never fabricates a number: a surface-radar range matches distanceM between the two real units at that time', () => {
    const sr = jtfRecords.find((r) => r.feed === 'surface-radar')!;
    expect(sr).toBeDefined();
    const detectorIdx = jtf.units.findIndex((u) => u.id === sr.byUnitId);
    const targetIdx = jtf.units.findIndex((u) => u.id === sr.aboutUnitIds[0]);
    const detectorState = unitStateAt(jtfTraj, detectorIdx, sr.tS);
    const targetState = unitStateAt(jtfTraj, targetIdx, sr.tS);
    const expectedRangeM = distanceM(detectorState, targetState);
    const raw = JSON.parse(sr.raw) as { rangeM: number };
    expect(raw.rangeM).toBeCloseTo(expectedRangeM, 0);
    const rangeField = sr.fields.find(([k]) => k === 'Range')![1];
    expect(parseFloat(rangeField)).toBeCloseTo(expectedRangeM / 1852, 1);
  });
});

describe('the catalog', () => {
  it('has one entry per feed, in FEEDS order, whether or not it has records', () => {
    const catalog = catalogOf(jtf, jtfRecords);
    expect(catalog.map((c) => c.feed.id)).toEqual(FEEDS.map((f) => f.id));
  });

  it('counts and time range match what deriveRecords actually produced', () => {
    for (const entry of catalogOf(salvo, salvoRecords)) {
      const forFeed = salvoRecords.filter((r) => r.feed === entry.feed.id);
      expect(entry.records).toBe(forFeed.length);
      if (forFeed.length === 0) {
        expect(entry.firstS).toBeNull();
        expect(entry.lastS).toBeNull();
        expect(entry.platforms).toEqual([]);
      } else {
        expect(entry.firstS).toBe(Math.min(...forFeed.map((r) => r.tS)));
        expect(entry.lastS).toBe(Math.max(...forFeed.map((r) => r.tS)));
        expect(entry.platforms.length).toBeGreaterThan(0);
      }
    }
  });

  it('names platforms, not raw ids, when the unit has a name', () => {
    const entry = catalogOf(jtf, jtfRecords).find((c) => c.feed.id === 'weapons')!;
    expect(entry.platforms).not.toContain('cvn1');
    expect(entry.platforms.some((p) => /Carrier|Cruiser|Destroyer|Frigate/.test(p))).toBe(true);
  });
});

describe('fmv and overhead: the two feeds with no real sensor behind them', () => {
  it('only exist when the run has a UAV or a helicopter', () => {
    expect(jtf.units.some((u) => u.classId === 'UAV' || u.classId === 'HELO')).toBe(true);
    expect(salvo.units.some((u) => u.classId === 'UAV' || u.classId === 'HELO')).toBe(true);
    expect(jtfRecords.some((r) => r.feed === 'fmv')).toBe(true);
    expect(salvoRecords.some((r) => r.feed === 'fmv')).toBe(true);

    const noAir = scenario([unit({ id: 'cg1', classId: 'CG' })]);
    const noAirRecords = deriveRecords(noAir, runScenario(noAir));
    expect(noAirRecords.some((r) => r.feed === 'fmv')).toBe(false);
  });

  it('says plainly that there is no imagery, on both feeds', () => {
    for (const r of jtfRecords.filter((r) => r.feed === 'fmv' || r.feed === 'overhead')) {
      expect(r.fields.some(([k, v]) => k === 'Imagery' && /no image/i.test(v))).toBe(true);
    }
  });

  it('runs a documented, fixed number of overhead passes spaced evenly across the run', () => {
    const passes = jtfRecords.filter((r) => r.feed === 'overhead').sort((a, b) => a.tS - b.tS);
    expect(passes).toHaveLength(OVERHEAD_PASSES);
    expect(OVERHEAD_PASSES).toBeGreaterThanOrEqual(3);
    expect(OVERHEAD_PASSES).toBeLessThanOrEqual(6);
    const cadenceS = jtf.durationS / (OVERHEAD_PASSES - 1);
    for (let i = 0; i < passes.length; i++) expect(passes[i].tS).toBeCloseTo(i * cadenceS, 0);
    expect(passes[0].tS).toBe(0);
    expect(passes.at(-1)!.tS).toBe(jtf.durationS);
    // Standing collection: it is not provenance for any one event.
    expect(passes.every((r) => r.eventIndex === undefined)).toBe(true);
  });

  it('overhead passes are not tied to an event, but fmv frames are', () => {
    const fmv = salvoRecords.filter((r) => r.feed === 'fmv');
    expect(fmv.length).toBeGreaterThan(0);
    expect(fmv.every((r) => r.eventIndex !== undefined)).toBe(true);
  });
});
