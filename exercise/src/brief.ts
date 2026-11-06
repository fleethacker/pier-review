import { formatClock, formatLatLon } from './geo';
import { SHIP_CLASSES, isPlatform } from './ships';
import { seaStateFromWind } from './sim';
import type { Trajectory } from './sim';
import { inOrder } from './storyboard';
import type { ScenarioConfig } from './types';

/**
 * The storyboard as a brief: the slides an exercise would be read out from — what it was for, who was in it, what the
 * weather was doing, what happened beat by beat, and what it cost — assembled from the run itself. This file builds the
 * content; `briefPptx.ts` turns it into a PowerPoint file.
 *
 * Everything here is read off the scenario and the trajectory. Where a figure is a modelling assumption rather than an
 * observation, the slide says so, and the last slide sets out what the figures are and are not.
 */

export const CLASSIFICATION = 'UNCLASSIFIED';

export type SlideKind = 'title' | 'bullets' | 'table' | 'moment' | 'outcome';

export interface BriefSlide {
  kind: SlideKind;
  /** The heading on the slide. */
  title: string;
  /** A line under the heading. */
  subtitle?: string;
  bullets?: string[];
  rows?: [string, string][];
  /** A storyboard picture, for a moment slide. */
  image?: string;
  caption?: string;
  /** Seconds into the exercise, shown as the time group on a moment slide. */
  atS?: number;
}

export interface Brief {
  /** The exercise, for the title slide and the running footer. */
  name: string;
  classification: string;
  /** When the deck was made, as an ISO string. Passed in so the same run always makes the same deck. */
  preparedAt: string;
  slides: BriefSlide[];
}

/** A name for a saved brief, dated from when it was prepared rather than from the clock. */
export function briefFilename(brief: Brief, extension: 'pptx' | 'html'): string {
  const day = brief.preparedAt.slice(0, 10).replace(/-/g, '');
  const name = brief.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'exercise';
  return `brief-${name}-${day}.${extension}`;
}

const bearing = (deg: number) => `${Math.round(deg).toString().padStart(3, '0')}°T`;

/** Sentences of a description, so a paragraph can become bullets without inventing wording. */
function sentences(text: string): string[] {
  return text
    .split(/(?<=\.)\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Units by side, counted by class, biggest group first. */
function orderOfBattle(scenario: ScenarioConfig, side: ScenarioConfig['units'][number]['side']): string[] {
  const counts = new Map<string, number>();
  for (const u of scenario.units) {
    if (u.side !== side) continue;
    const label = SHIP_CLASSES[u.classId].name;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([label, n]) => `${n} × ${label}`);
}

/** What the run cost, counted off its own events. */
export interface Outcome {
  hits: number;
  intercepts: number;
  mines: number;
  blueLost: string[];
  redLost: string[];
}

export function outcomeOf(scenario: ScenarioConfig, trajectory: Trajectory): Outcome {
  const byId = new Map(scenario.units.map((u) => [u.id, u]));
  const out: Outcome = { hits: 0, intercepts: 0, mines: 0, blueLost: [], redLost: [] };
  for (const e of trajectory.events) {
    if (e.type === 'hit') out.hits++;
    else if (e.type === 'mine') {
      out.hits++;
      out.mines++;
    } else if (e.type === 'intercept') out.intercepts++;
    else if (e.type === 'destroyed') {
      const u = byId.get(e.unitId);
      if (!u || !isPlatform(SHIP_CLASSES[u.classId])) continue;
      if (u.side === 'BLUE') out.blueLost.push(u.name);
      if (u.side === 'RED') out.redLost.push(u.name);
    }
  }
  return out;
}

/** Build the brief. `preparedAt` is passed in rather than read from the clock, so the same run always gives the same deck. */
export function buildBrief(scenario: ScenarioConfig, trajectory: Trajectory, preparedAt: string): Brief {
  const moments = inOrder(scenario.storyboard ?? []);
  const name = (id: string | undefined) => (id ? (scenario.units.find((u) => u.id === id)?.name ?? id) : undefined);
  const env = scenario.environment;
  const sea = seaStateFromWind(env.windKt);
  const out = outcomeOf(scenario, trajectory);
  const platforms = scenario.units.filter((u) => isPlatform(SHIP_CLASSES[u.classId]));
  const slides: BriefSlide[] = [];

  slides.push({
    kind: 'title',
    title: scenario.name,
    subtitle: 'Exercise storyboard brief',
    rows: [
      ['Exercise length', formatClock(scenario.durationS)],
      ['Units', `${scenario.units.length} (${platforms.length} ships and aircraft)`],
      ['Storyboard', `${moments.length} moment${moments.length === 1 ? '' : 's'}`],
      ['Area', formatLatLon(scenario.center)],
      ['Prepared', preparedAt],
    ],
  });

  slides.push({
    kind: 'bullets',
    title: 'Purpose',
    subtitle: 'What this exercise sets out to show',
    bullets: [
      ...sentences(scenario.description),
      `The storyboard that follows covers ${moments.length} moment${moments.length === 1 ? '' : 's'} across ${formatClock(scenario.durationS)} of exercise time.`,
    ],
  });

  const blue = orderOfBattle(scenario, 'BLUE');
  const red = orderOfBattle(scenario, 'RED');
  const neutral = orderOfBattle(scenario, 'NEUTRAL');
  slides.push({
    kind: 'bullets',
    title: 'Situation — order of battle',
    subtitle: `${platforms.length} ships and aircraft, ${scenario.units.length - platforms.length} weapons and mines`,
    bullets: [
      `Blue: ${blue.length ? blue.join(', ') : 'none'}`,
      `Opposing force: ${red.length ? red.join(', ') : 'none'}`,
      ...(neutral.length ? [`Neutral: ${neutral.join(', ')}`] : []),
      `Starting position of the main group: ${formatLatLon(scenario.center)}`,
    ],
  });

  slides.push({
    kind: 'table',
    title: 'Conditions',
    subtitle: 'Weather, sea and light as modelled for this run',
    rows: [
      ['Wind', `${env.windKt} kt from ${bearing(env.windFromDeg)}`],
      ['Current', `${env.currentKt} kt toward ${bearing(env.currentToDeg)}`],
      ['Sea state', `${sea} (derived from the wind speed)`],
      ['Light', scenario.lightPreset],
      ['Sea state slows small craft', scenario.seaState ? 'yes' : 'no'],
      ['Sensors and detection modelled', scenario.detection ? 'yes' : 'no'],
      ['Chance seed', `${scenario.seed ?? 1}`],
    ],
  });

  if (moments.length) {
    slides.push({
      kind: 'bullets',
      title: 'Execution — sequence of events',
      subtitle: 'The beats that follow, in order',
      bullets: moments.map((m) => `T+${formatClock(m.atS)}  ${m.title}`),
    });
    for (const m of moments) {
      slides.push({
        kind: 'moment',
        title: m.title,
        subtitle: name(m.unitId),
        atS: m.atS,
        image: m.image,
        caption: m.caption,
      });
    }
  }

  slides.push({
    kind: 'outcome',
    title: 'Outcome',
    subtitle: 'Counted from this run',
    rows: [
      ['Hits on ships and aircraft', `${out.hits}`],
      ['Weapons shot down', `${out.intercepts}`],
      ...(out.mines ? ([['Mine strikes', `${out.mines}`]] as [string, string][]) : []),
      ['Blue losses', out.blueLost.length ? `${out.blueLost.length} — ${out.blueLost.join(', ')}` : 'none'],
      ['Opposing losses', out.redLost.length ? `${out.redLost.length} — ${out.redLost.join(', ')}` : 'none'],
      ['Events in all', `${trajectory.events.length}`],
    ],
  });

  slides.push({
    kind: 'bullets',
    title: 'Assumptions and limitations',
    subtitle: 'Read the figures above with these in mind',
    bullets: [
      'This is a simulation. Ship dimensions, handling, sensor ranges, weapon damage and hit chances are illustrative figures, not operational data.',
      scenario.detection
        ? 'Detection is deterministic: a unit in range and above the radar horizon is seen. There is no probability of detection.'
        : 'Sensors and detection are switched off in this run: every unit acts on perfect knowledge of the others.',
      'One run is a single roll of the dice. Use the red team to ask how often an outcome happens, and over what range of conditions.',
      'Any collected record shown alongside an event is synthesised from this simulation, not a real observation.',
      'Decision support for a demonstrator. Not navigational guidance, and not a record of a real exercise.',
    ],
  });

  return { name: scenario.name, classification: CLASSIFICATION, preparedAt, slides };
}
