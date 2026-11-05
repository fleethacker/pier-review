import { at, minefield, OCEAN_CENTER, station } from './scenarioKit';
import { offsetM } from './geo';
import type { ClassId, LonLat, OutcomeSpec, Perturbation, ScenarioConfig, Side, UnitConfig } from './types';

/**
 * Three large scenarios that use everything: surface groups, submarines, helicopters, fixed-wing aircraft, early-warning
 * aircraft, surveillance and attack drones, mines, missiles and torpedoes, with sensors and rough seas on. Built from small
 * helpers so a salvo of drones is one line, not twelve.
 */

interface ShipOptions extends Partial<UnitConfig> {
  leader?: string;
  ahead?: number;
  abeam?: number;
}

/** A unit that keeps station on `leader` from the start. */
function escort(id: string, name: string, classId: ClassId, side: Side, origin: LonLat, headingDeg: number, speedKt: number, o: ShipOptions & { leader: string; ahead: number; abeam: number }): UnitConfig {
  const { leader, ahead, abeam, ...rest } = o;
  return { id, name, classId, side, start: station(origin, headingDeg, ahead, abeam), headingDeg, speedKt, behavior: { type: 'escort', leaderId: leader, aheadM: ahead, abeamM: abeam }, ...rest };
}

/** `count` weapons of one class fired by `launcher` from `firstAtS`, `gapS` apart, at `targets` in turn. */
function salvo(prefix: string, classId: ClassId, launcher: UnitConfig, count: number, firstAtS: number, gapS: number, targets: string[], side: Side = launcher.side): UnitConfig[] {
  const names: Partial<Record<ClassId, string>> = { ASM: 'Missile', DRONE: 'Drone', TORP: 'Torpedo' };
  return Array.from({ length: count }, (_, i): UnitConfig => ({
    id: `${prefix}${i + 1}`,
    name: `${names[classId] ?? classId} ${prefix.toUpperCase()}${i + 1}`,
    classId,
    side,
    start: launcher.start,
    headingDeg: launcher.headingDeg,
    speedKt: classId === 'TORP' ? 45 : classId === 'DRONE' ? 90 : 300,
    launch: { byId: launcher.id, atS: firstAtS + i * gapS },
    behavior: { type: 'strike', targetId: targets[i % targets.length] },
  }));
}

const ids = (units: UnitConfig[]) => units.map((u) => u.id);
const hit = (id: string, label: string, unitId: string, extra: Partial<OutcomeSpec> = {}): OutcomeSpec => ({ id, label, type: 'hit', unitId, ...extra }) as OutcomeSpec;
const wind = (sd: number): Perturbation => ({ id: 'wind', label: 'Wind speed', target: { kind: 'environment', field: 'windKt' }, mode: 'add', dist: { type: 'normal', mean: 0, sd } });

// ---------------------------------------------------------------------------------------------------------------------
// 1. Joint task force: a carrier group with its air wing and ASW screen against a surface group, two submarines, an air
//    raid, a drone swarm from a merchant mothership and a minefield on the track.
// ---------------------------------------------------------------------------------------------------------------------

const JTF = at(-34000, -5000);

function jointTaskForce(): ScenarioConfig {
  const cvn: UnitConfig = { id: 'cvn1', name: 'Carrier 1', classId: 'CVN', side: 'BLUE', start: JTF, headingDeg: 90, speedKt: 18, maxTurnRateDegPerS: 0.1, decoys: 6, pDecoy: 0.4, behavior: { type: 'route', waypoints: [offsetM(JTF, 80000, 0)] } };
  const blue: UnitConfig[] = [
    cvn,
    escort('cg1', 'Cruiser 1', 'CG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: 3500, abeam: 0, decoys: 4 }),
    escort('cg2', 'Cruiser 2', 'CG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: -3500, abeam: 0, decoys: 4 }),
    escort('ddg1', 'Destroyer 1', 'DDG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: 2000, abeam: -4500, decoys: 4 }),
    escort('ddg2', 'Destroyer 2', 'DDG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: 2000, abeam: 4500, decoys: 4 }),
    escort('ddg3', 'Destroyer 3', 'DDG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: -2500, abeam: -5500, decoys: 4 }),
    escort('ddg4', 'Destroyer 4', 'DDG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: -2500, abeam: 5500, decoys: 4 }),
    escort('ffg1', 'Frigate 1', 'FFG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: 8000, abeam: -3000, decoys: 3 }),
    escort('ffg2', 'Frigate 2', 'FFG', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: 8000, abeam: 3000, decoys: 3 }),
    escort('lhd1', 'Amphibious ship 1', 'LHD', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: -6500, abeam: 1500, decoys: 4 }),
    escort('sup1', 'Supply ship', 'CARGO', 'BLUE', JTF, 90, 18, { leader: 'cvn1', ahead: -9500, abeam: -1500 }),
    // Air: early warning orbiting ahead, four fighters on station, two ASW helicopters sweeping ahead, a drone scouting far ahead.
    { id: 'aew1', name: 'Early warning', classId: 'AEW', side: 'BLUE', start: offsetM(JTF, 20000, 0), headingDeg: 90, speedKt: 250, altitudeM: 8000, behavior: { type: 'loiter', center: offsetM(JTF, 24000, 0), radiusM: 15000 } },
    ...[0, 1, 2, 3].map((i): UnitConfig => ({ id: `bf${i + 1}`, name: `Fighter ${i + 1}`, classId: 'FIGHTER', side: 'BLUE', start: offsetM(JTF, 15000, (i - 1.5) * 6000), headingDeg: 90, speedKt: 380, altitudeM: 6000, behavior: { type: 'loiter', center: offsetM(JTF, 38000, (i - 1.5) * 12000), radiusM: 9000 } })),
    ...[0, 1].map((i): UnitConfig => ({ id: `bh${i + 1}`, name: `ASW helicopter ${i + 1}`, classId: 'HELO', side: 'BLUE', start: offsetM(JTF, 6000, (i ? 1 : -1) * 3000), headingDeg: 90, speedKt: 90, altitudeM: 100, behavior: { type: 'route', waypoints: [offsetM(JTF, 30000, (i ? 1 : -1) * 6000), offsetM(JTF, 30000, (i ? 1 : -1) * -2000), offsetM(JTF, 12000, (i ? 1 : -1) * -2000), offsetM(JTF, 12000, (i ? 1 : -1) * 6000)], loop: true } })),
    { id: 'buav1', name: 'Scout drone', classId: 'UAV', side: 'BLUE', start: JTF, headingDeg: 90, speedKt: 120, launch: { byId: 'cvn1', atS: 60 }, behavior: { type: 'route', waypoints: [{ ...offsetM(JTF, 110000, -6000), altitudeM: 3000 }] } },
  ];

  const rdd1: UnitConfig = { id: 'rdd1', name: 'Hostile destroyer 1', classId: 'DDG', side: 'RED', start: at(62000, -3000), headingDeg: 270, speedKt: 18, behavior: { type: 'route', waypoints: [at(10000, -3000)] } };
  const rdd2: UnitConfig = { id: 'rdd2', name: 'Hostile destroyer 2', classId: 'DDG', side: 'RED', start: at(64000, -9000), headingDeg: 270, speedKt: 18, behavior: { type: 'route', waypoints: [at(10000, -8000)] } };
  const rmother: UnitConfig = { id: 'rmother', name: 'Merchant (drone carrier)', classId: 'CARGO', side: 'RED', start: at(58000, 6000), headingDeg: 270, speedKt: 10, behavior: { type: 'route', waypoints: [at(30000, 4000)] } };
  const rsub1: UnitConfig = { id: 'rsub1', name: 'Hostile submarine 1', classId: 'SSN', side: 'RED', start: at(-4000, -3500), headingDeg: 270, speedKt: 5, behavior: { type: 'hold' } };
  const rsub2: UnitConfig = { id: 'rsub2', name: 'Hostile submarine 2', classId: 'SSK', side: 'RED', start: at(2000, -9000), headingDeg: 270, speedKt: 4, behavior: { type: 'hold' } };
  const facs = [0, 1, 2, 3].map((i): UnitConfig => ({ id: `rfac${i + 1}`, name: `Fast attack craft ${i + 1}`, classId: 'FAC', side: 'RED', start: at(60000 + i * 800, -14000 - i * 1500), headingDeg: 270, speedKt: 38, behavior: { type: 'pursue', targetId: ['ddg3', 'ddg4', 'lhd1', 'sup1'][i], standoffM: 6000 } }));
  const raiders = [0, 1, 2, 3, 4, 5].map((i): UnitConfig => ({ id: `rf${i + 1}`, name: `Raider ${i + 1}`, classId: 'FIGHTER', side: 'RED', start: at(105000 + i * 1500, -5000 + (i - 2.5) * 5000), headingDeg: 270, speedKt: 450, altitudeM: 5000, behavior: { type: 'route', waypoints: [at(70000, -5000 + (i - 2.5) * 5000), at(76000, -5000 + (i - 2.5) * 5000)], loop: true } }));
  const ruav: UnitConfig = { id: 'ruav1', name: 'Hostile scout drone', classId: 'UAV', side: 'RED', start: at(90000, 0), headingDeg: 270, speedKt: 130, altitudeM: 3000, behavior: { type: 'route', waypoints: [{ ...at(45000, -2000), altitudeM: 3000 }, { ...at(60000, 6000), altitudeM: 3000 }], loop: true } };

  const blueTargets = ['cvn1', 'cg1', 'ddg1', 'ddg2'];
  const red: UnitConfig[] = [
    rdd1, rdd2, rmother, rsub1, rsub2, ...facs, ...raiders, ruav,
    ...salvo('ra', 'ASM', rdd1, 8, 120, 1, ['cvn1']),
    ...salvo('rb', 'ASM', rdd2, 8, 120, 1, ['cvn1', 'cg1']),
    ...raiders.flatMap((r, i) => salvo(`rc${i + 1}x`, 'ASM', r, 3, 150, 2, [blueTargets[i % 4], 'cvn1'])),
    ...facs.flatMap((f, i) => salvo(`rd${i + 1}x`, 'ASM', f, 2, 200 + i * 10, 5, [['ddg3', 'ddg4', 'lhd1', 'sup1'][i]])),
    ...salvo('dr', 'DRONE', rmother, 20, 240, 10, ['ddg1', 'ddg2', 'cg1', 'cg2', 'ddg3', 'ddg4']),
    ...salvo('tp1x', 'TORP', rsub1, 3, 150, 25, ['cvn1', 'cvn1', 'cg1']),
    ...salvo('tp2x', 'TORP', rsub2, 2, 200, 25, ['ddg1', 'ddg2']),
    ...minefield(22, -16000, -5000, 4500, 6000, 31),
  ];
  const bluePunch: UnitConfig[] = [
    ...salvo('bt', 'TORP', blue.find((u) => u.id === 'ffg1')!, 1, 60, 1, ['rsub1'], 'BLUE'),
    ...salvo('bu', 'TORP', blue.find((u) => u.id === 'bh1')!, 1, 60, 1, ['rsub2'], 'BLUE'),
  ];
  const drones = ids(red).filter((id) => /^dr\d+$/.test(id));

  return {
    id: 'joint-task-force',
    name: 'Joint task force against a combined attack',
    description:
      'A carrier group with its air wing, early warning, anti-submarine helicopters and a frigate screen steams east into a combined attack: two destroyers and four fast attack craft, six raiders, two submarines waiting on the track, twenty attack drones from a merchant mothership and a minefield. Sensors, rough seas and decoys are on, so who finds whom first decides the day. More than a hundred units: let it run, then open Red team.',
    center: OCEAN_CENTER,
    durationS: 3000,
    lightPreset: 'dusk',
    seed: 11,
    detection: true,
    seaState: true,
    environment: { windFromDeg: 260, windKt: 14, currentToDeg: 60, currentKt: 0.7 },
    units: [...blue, ...bluePunch, ...red],
    redTeam: {
      runs: 20,
      seed: 3,
      outcomes: [
        hit('cvn-hit', 'The carrier is hit', 'cvn1'),
        { id: 'loss', label: 'At least one blue ship or aircraft is lost', type: 'side_losses', side: 'BLUE', atLeast: 1 },
        { id: 'loss3', label: 'Three or more blue losses', type: 'side_losses', side: 'BLUE', atLeast: 3 },
        { id: 'mine', label: 'A ship hits a mine', type: 'mine_strike' },
        { id: 's1', label: 'Submarine 1 found by blue', type: 'detected', unitId: 'rsub1', bySide: 'BLUE' },
        { id: 's2', label: 'Submarine 2 found by blue', type: 'detected', unitId: 'rsub2', bySide: 'BLUE' },
        { id: 'sub-found', label: 'The task force finds a submarine', type: 'any', of: ['s1', 's2'] },
        { id: 'cvn-seen', label: 'The carrier is detected by red', type: 'detected', unitId: 'cvn1', bySide: 'RED' },
      ] as OutcomeSpec[],
      perturbations: [
        wind(5),
        { id: 'aew', label: 'Early-warning aircraft is up (0 = yes, 1 = left out)', target: { kind: 'unit', unitId: 'aew1', field: 'disabled' }, mode: 'set', dist: { type: 'choice', values: [0, 1], weights: [3, 1] } },
        { id: 'cvn-sig', label: 'Carrier radar signature', target: { kind: 'unit', unitId: 'cvn1', field: 'signature' }, mode: 'set', dist: { type: 'uniform', min: 0.4, max: 1 } },
        { id: 'sub1-n', label: 'Submarine 1 position (north)', target: { kind: 'unit', unitId: 'rsub1', field: 'startNorthM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 3000 } },
        { id: 'drone-t', label: 'Drone launch time', target: { kind: 'unit', unitId: 'dr1', field: 'launchAtS' }, mode: 'add', dist: { type: 'uniform', min: -60, max: 120 } },
      ],
      sweep: { target: { kind: 'salvo', unitIds: drones }, values: [0, 5, 10, 20] },
    },
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// 2. Convoy escort: merchant ships through a strait with three submarines, mines, fast attack craft and a scouting raid.
// ---------------------------------------------------------------------------------------------------------------------

const CONVOY = at(-30000, 0);

function convoyEscort(): ScenarioConfig {
  const lead: UnitConfig = { id: 'mv1', name: 'Merchant 1', classId: 'CARGO', side: 'BLUE', start: CONVOY, headingDeg: 90, speedKt: 11, maxTurnRateDegPerS: 0.15, behavior: { type: 'route', waypoints: [offsetM(CONVOY, 70000, 0)] } };
  const merchants: UnitConfig[] = [
    lead,
    escort('mv2', 'Merchant 2', 'CARGO', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -900, abeam: 0 }),
    escort('mv3', 'Merchant 3', 'CARGO', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -1800, abeam: 0 }),
    escort('mv4', 'Merchant 4', 'CARGO', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: 0, abeam: 1600 }),
    escort('mv5', 'Merchant 5', 'CARGO', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -900, abeam: 1600 }),
    escort('mv6', 'Merchant 6', 'CARGO', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -1800, abeam: 1600 }),
  ];
  const escorts: UnitConfig[] = [
    escort('ddg1', 'Destroyer 1', 'DDG', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: 4500, abeam: 400, decoys: 4, pDecoy: 0.45 }),
    escort('ffg1', 'Frigate 1', 'FFG', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: 3000, abeam: -3000, decoys: 3, pDecoy: 0.45 }),
    escort('ffg2', 'Frigate 2', 'FFG', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: 3000, abeam: 4700, decoys: 3, pDecoy: 0.45 }),
    escort('ddg2', 'Destroyer 2', 'DDG', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -3500, abeam: 800, decoys: 4, pDecoy: 0.45 }),
    escort('cg1', 'Cruiser 1', 'CG', 'BLUE', CONVOY, 90, 11, { leader: 'mv1', ahead: -1000, abeam: 3300, decoys: 4, pDecoy: 0.45 }),
  ];
  const air: UnitConfig[] = [
    ...[0, 1].map((i): UnitConfig => ({ id: `bh${i + 1}`, name: `ASW helicopter ${i + 1}`, classId: 'HELO', side: 'BLUE', start: offsetM(CONVOY, 8000, i ? 4000 : -3000), headingDeg: 90, speedKt: 80, altitudeM: 90, behavior: { type: 'route', waypoints: [offsetM(CONVOY, 22000, i ? 5000 : -4000), offsetM(CONVOY, 22000, i ? -1000 : -9000), offsetM(CONVOY, 10000, i ? -1000 : -9000), offsetM(CONVOY, 10000, i ? 5000 : -4000)], loop: true } })),
    { id: 'buav1', name: 'Convoy drone', classId: 'UAV', side: 'BLUE', start: offsetM(CONVOY, 4000, 0), headingDeg: 90, speedKt: 90, altitudeM: 2500, behavior: { type: 'loiter', center: offsetM(CONVOY, 22000, 1000), radiusM: 12000 } },
    { id: 'bf1', name: 'Fighter 1', classId: 'FIGHTER', side: 'BLUE', start: offsetM(CONVOY, 10000, 3000), headingDeg: 90, speedKt: 350, altitudeM: 5000, behavior: { type: 'loiter', center: offsetM(CONVOY, 30000, 5000), radiusM: 9000 } },
    { id: 'bf2', name: 'Fighter 2', classId: 'FIGHTER', side: 'BLUE', start: offsetM(CONVOY, 10000, -4000), headingDeg: 90, speedKt: 350, altitudeM: 5000, behavior: { type: 'loiter', center: offsetM(CONVOY, 30000, -6000), radiusM: 9000 } },
  ];
  const subs: UnitConfig[] = [
    { id: 'rsub1', name: 'Hostile submarine 1', classId: 'SSK', side: 'RED', start: at(-6000, 1500), headingDeg: 270, speedKt: 4, behavior: { type: 'hold' } },
    { id: 'rsub2', name: 'Hostile submarine 2', classId: 'SSN', side: 'RED', start: at(10000, -3000), headingDeg: 270, speedKt: 5, behavior: { type: 'hold' } },
    { id: 'rsub3', name: 'Hostile submarine 3', classId: 'SSK', side: 'RED', start: at(20000, 3500), headingDeg: 270, speedKt: 4, behavior: { type: 'hold' } },
  ];
  const facs = [0, 1, 2, 3].map((i): UnitConfig => ({ id: `rfac${i + 1}`, name: `Fast attack craft ${i + 1}`, classId: 'FAC', side: 'RED', start: at(30000 + i * 700, 24000 + i * 1200), headingDeg: 200, speedKt: 40, behavior: { type: 'pursue', targetId: ['mv4', 'mv5', 'mv6', 'mv1'][i], standoffM: 5000 } }));
  const raiders = [0, 1].map((i): UnitConfig => ({ id: `rf${i + 1}`, name: `Raider ${i + 1}`, classId: 'FIGHTER', side: 'RED', start: at(90000, i ? 12000 : -12000), headingDeg: 270, speedKt: 450, altitudeM: 5000, behavior: { type: 'route', waypoints: [at(55000, i ? 8000 : -8000), at(61000, i ? 8000 : -8000)], loop: true } }));
  const mother: UnitConfig = { id: 'rmother', name: 'Trawler (drone carrier)', classId: 'CARGO', side: 'RED', start: at(36000, -24000), headingDeg: 160, speedKt: 8, behavior: { type: 'route', waypoints: [at(24000, -13000)] } };
  const red: UnitConfig[] = [
    ...subs, mother, ...facs, ...raiders,
    ...salvo('dr', 'DRONE', mother, 8, 500, 15, ['mv5', 'mv6', 'cg1', 'ffg2']),
    ...salvo('s1t', 'TORP', subs[0], 3, 100, 20, ['mv1', 'mv2', 'ddg2']),
    ...salvo('s2t', 'TORP', subs[1], 3, 100, 20, ['ddg1', 'mv4', 'mv5']),
    ...salvo('s3t', 'TORP', subs[2], 3, 100, 20, ['mv3', 'mv6', 'cg1']),
    ...facs.flatMap((f, i) => salvo(`f${i + 1}x`, 'ASM', f, 2, 300 + i * 20, 6, [['mv4', 'mv5', 'mv6', 'mv1'][i]])),
    ...raiders.flatMap((r, i) => salvo(`r${i + 1}x`, 'ASM', r, 3, 200 + i * 30, 5, ['mv1', 'mv4', 'mv6'])),
    ...minefield(30, -16000, 0, 5000, 5000, 17),
  ];
  const blueTorps: UnitConfig[] = [
    ...salvo('bt1', 'TORP', escorts[1], 1, 60, 1, ['rsub1'], 'BLUE'),
    ...salvo('bt2', 'TORP', escorts[2], 1, 60, 1, ['rsub3'], 'BLUE'),
    ...salvo('bt3', 'TORP', air[0], 1, 60, 1, ['rsub2'], 'BLUE'),
  ];
  const guard = ['ddg1', 'ffg1', 'ffg2', 'ddg2', 'cg1'];
  const cargoIds = merchants.map((m) => m.id);

  return {
    id: 'convoy-escort',
    name: 'Convoy through a submarine strait',
    description:
      'Six merchant ships and five escorts push east through a strait where three submarines lie in wait, a minefield sits on the track, four fast attack craft come in from the north, a trawler launches attack drones from the south and two raiders fire from the east. Two ASW helicopters and a drone work ahead of the convoy. Open Red team and sweep how many escorts there are: that is the question a convoy planner asks.',
    center: OCEAN_CENTER,
    durationS: 3600,
    lightPreset: 'night',
    seed: 5,
    detection: true,
    seaState: true,
    environment: { windFromDeg: 310, windKt: 16, currentToDeg: 80, currentKt: 0.9 },
    units: [...merchants, ...escorts, ...air, ...blueTorps, ...red],
    redTeam: {
      runs: 30,
      seed: 9,
      outcomes: [
        { id: 'mv-loss', label: 'At least one merchant ship is lost', type: 'side_losses', side: 'BLUE', atLeast: 1 },
        { id: 'mv-loss3', label: 'Three or more blue losses', type: 'side_losses', side: 'BLUE', atLeast: 3 },
        ...cargoIds.slice(0, 3).map((id) => ({ id: `${id}-hit`, label: `${id.replace('mv', 'Merchant ')} is hit`, type: 'hit' as const, unitId: id })),
        { id: 'mine', label: 'A ship hits a mine', type: 'mine_strike' },
        { id: 'd1', label: 'Submarine 1 found', type: 'detected', unitId: 'rsub1', bySide: 'BLUE' },
        { id: 'd2', label: 'Submarine 2 found', type: 'detected', unitId: 'rsub2', bySide: 'BLUE' },
        { id: 'd3', label: 'Submarine 3 found', type: 'detected', unitId: 'rsub3', bySide: 'BLUE' },
        { id: 'sub-any', label: 'The escorts find a submarine', type: 'any', of: ['d1', 'd2', 'd3'] },
      ] as OutcomeSpec[],
      perturbations: [
        wind(6),
        { id: 'sub2-n', label: 'Submarine 2 position (north)', target: { kind: 'unit', unitId: 'rsub2', field: 'startNorthM' }, mode: 'add', dist: { type: 'normal', mean: 0, sd: 3500 } },
        { id: 'mines', label: 'Mine hit chance', target: { kind: 'unit', unitId: 'mine01', field: 'pHit' }, mode: 'set', dist: { type: 'uniform', min: 0.4, max: 0.9 } },
        { id: 'fac-t', label: 'Fast attack craft arrive', target: { kind: 'unit', unitId: 'f1x1', field: 'launchAtS' }, mode: 'add', dist: { type: 'uniform', min: -120, max: 240 } },
      ],
      sweep: { target: { kind: 'salvo', unitIds: guard }, values: [1, 2, 3, 4, 5] },
    },
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// 3. Drone swarm: an amphibious group defends against waves of cheap drones, fast attack craft and a raid.
// ---------------------------------------------------------------------------------------------------------------------

const ARG = at(-14000, 0);

function droneSwarm(): ScenarioConfig {
  const lhd: UnitConfig = { id: 'lhd1', name: 'Amphibious ship 1', classId: 'LHD', side: 'BLUE', start: ARG, headingDeg: 90, speedKt: 14, maxTurnRateDegPerS: 0.15, decoys: 5, pDecoy: 0.4, behavior: { type: 'route', waypoints: [offsetM(ARG, 50000, 0)] } };
  const blue: UnitConfig[] = [
    lhd,
    escort('ddg1', 'Destroyer 1', 'DDG', 'BLUE', ARG, 90, 14, { leader: 'lhd1', ahead: 3500, abeam: -3500, decoys: 3, magazine: 12 }),
    escort('ddg2', 'Destroyer 2', 'DDG', 'BLUE', ARG, 90, 14, { leader: 'lhd1', ahead: 3500, abeam: 3500, decoys: 3, magazine: 12 }),
    escort('ddg3', 'Destroyer 3', 'DDG', 'BLUE', ARG, 90, 14, { leader: 'lhd1', ahead: -3500, abeam: 0, decoys: 3, magazine: 12 }),
    escort('ffg1', 'Frigate 1', 'FFG', 'BLUE', ARG, 90, 14, { leader: 'lhd1', ahead: 0, abeam: -6500, decoys: 2, magazine: 10 }),
    escort('ffg2', 'Frigate 2', 'FFG', 'BLUE', ARG, 90, 14, { leader: 'lhd1', ahead: 0, abeam: 6500, decoys: 2, magazine: 10 }),
    { id: 'aew1', name: 'Early warning', classId: 'AEW', side: 'BLUE', start: offsetM(ARG, 8000, 0), headingDeg: 90, speedKt: 240, altitudeM: 7500, behavior: { type: 'loiter', center: offsetM(ARG, 12000, 0), radiusM: 12000 } },
    ...[0, 1].map((i): UnitConfig => ({ id: `bf${i + 1}`, name: `Fighter ${i + 1}`, classId: 'FIGHTER', side: 'BLUE', start: offsetM(ARG, 5000, i ? 3000 : -3000), headingDeg: 90, speedKt: 350, altitudeM: 5000, behavior: { type: 'loiter', center: offsetM(ARG, 22000, i ? 9000 : -9000), radiusM: 8000 } })),
    ...[0, 1].map((i): UnitConfig => ({ id: `bh${i + 1}`, name: `Helicopter ${i + 1}`, classId: 'HELO', side: 'BLUE', start: offsetM(ARG, 2000, i ? 2000 : -2000), headingDeg: 90, speedKt: 18, altitudeM: 150, behavior: { type: 'escort', leaderId: 'lhd1', aheadM: 2500, abeamM: i ? 2500 : -2500 } })),
    { id: 'buav1', name: 'Scout drone', classId: 'UAV', side: 'BLUE', start: ARG, headingDeg: 90, speedKt: 100, launch: { byId: 'lhd1', atS: 30 }, behavior: { type: 'loiter', center: offsetM(ARG, 28000, 0), radiusM: 14000 } },
  ];
  const motherN: UnitConfig = { id: 'rmotherN', name: 'Drone carrier (north)', classId: 'CARGO', side: 'RED', start: at(26000, 22000), headingDeg: 200, speedKt: 8, behavior: { type: 'route', waypoints: [at(18000, 12000)] } };
  const motherS: UnitConfig = { id: 'rmotherS', name: 'Drone carrier (south)', classId: 'CARGO', side: 'RED', start: at(28000, -23000), headingDeg: 340, speedKt: 8, behavior: { type: 'route', waypoints: [at(20000, -13000)] } };
  const facs = [0, 1, 2, 3].map((i): UnitConfig => ({ id: `rfac${i + 1}`, name: `Fast attack craft ${i + 1}`, classId: 'FAC', side: 'RED', start: at(40000 + i * 600, i % 2 ? -5000 : 5000), headingDeg: 270, speedKt: 40, behavior: { type: 'pursue', targetId: ['ddg1', 'ddg2', 'ffg1', 'ffg2'][i], standoffM: 5000 } }));
  const raiders = [0, 1].map((i): UnitConfig => ({ id: `rf${i + 1}`, name: `Raider ${i + 1}`, classId: 'FIGHTER', side: 'RED', start: at(85000, i ? 6000 : -6000), headingDeg: 270, speedKt: 450, altitudeM: 5000, behavior: { type: 'route', waypoints: [at(50000, i ? 4000 : -4000), at(56000, i ? 4000 : -4000)], loop: true } }));
  const ruav: UnitConfig = { id: 'ruav1', name: 'Hostile scout drone', classId: 'UAV', side: 'RED', start: at(60000, 0), headingDeg: 270, speedKt: 110, altitudeM: 3000, behavior: { type: 'route', waypoints: [{ ...at(30000, 4000), altitudeM: 3000 }, { ...at(30000, -4000), altitudeM: 3000 }], loop: true } };
  const waveTargets = ['ddg1', 'ddg2', 'lhd1', 'ffg1', 'ffg2', 'ddg3'];
  const red: UnitConfig[] = [
    motherN, motherS, ...facs, ...raiders, ruav,
    ...salvo('dn', 'DRONE', motherN, 16, 200, 8, waveTargets),
    ...salvo('ds', 'DRONE', motherS, 16, 260, 8, waveTargets.slice().reverse()),
    ...facs.flatMap((f, i) => salvo(`f${i + 1}x`, 'ASM', f, 2, 260 + i * 8, 5, ['lhd1', 'ddg2', 'lhd1', 'ddg1'].slice(i, i + 1))),
    ...raiders.flatMap((r, i) => salvo(`r${i + 1}x`, 'ASM', r, 3, 180 + i * 25, 4, ['lhd1'])),
  ];
  const swarm = ids(red).filter((id) => /^d[ns]\d+$/.test(id));

  return {
    id: 'drone-swarm',
    name: 'Drone swarm defence',
    description:
      'An amphibious group with three destroyers, two frigates, early warning and a fighter pair is hit from two directions at once by thirty-two cheap attack drones launched from two disguised merchant ships, four fast attack craft and two raiders with missiles. The destroyers have a limited magazine, so the question is how many shots it takes to stop a swarm. Open Red team and sweep the number of drones.',
    center: OCEAN_CENTER,
    durationS: 1800,
    lightPreset: 'dusk',
    seed: 8,
    detection: true,
    seaState: true,
    environment: { windFromDeg: 230, windKt: 12, currentToDeg: 30, currentKt: 0.6 },
    units: [...blue, ...red],
    redTeam: {
      runs: 30,
      seed: 4,
      outcomes: [
        hit('lhd-hit', 'The amphibious ship is hit', 'lhd1'),
        { id: 'loss', label: 'A blue ship or aircraft is lost', type: 'side_losses', side: 'BLUE', atLeast: 1 },
        { id: 'loss2', label: 'Two or more blue losses', type: 'side_losses', side: 'BLUE', atLeast: 2 },
        { id: 'shot20', label: 'At least 20 weapons shot down', type: 'intercepts', atLeast: 20 },
        { id: 'lhd-seen', label: 'The amphibious ship is detected by red', type: 'detected', unitId: 'lhd1', bySide: 'RED' },
      ],
      perturbations: [
        wind(5),
        { id: 'aew', label: 'Early-warning aircraft is up (0 = yes, 1 = left out)', target: { kind: 'unit', unitId: 'aew1', field: 'disabled' }, mode: 'set', dist: { type: 'choice', values: [0, 1], weights: [3, 1] } },
        { id: 'dn-t', label: 'North wave launch time', target: { kind: 'unit', unitId: 'dn1', field: 'launchAtS' }, mode: 'add', dist: { type: 'uniform', min: -60, max: 90 } },
        { id: 'pkill', label: 'Destroyer kill chance per shot', target: { kind: 'unit', unitId: 'ddg1', field: 'pKill' }, mode: 'set', dist: { type: 'uniform', min: 0.3, max: 0.6 } },
      ],
      sweep: { target: { kind: 'salvo', unitIds: swarm }, values: [8, 16, 24, 32] },
    },
  };
}

export const LARGE_SCENARIOS: ScenarioConfig[] = [jointTaskForce(), convoyEscort(), droneSwarm()];
