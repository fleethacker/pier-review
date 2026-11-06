import { describe, expect, it, vi } from 'vitest';
import { buildBrief, CLASSIFICATION, outcomeOf } from './brief';
import { formatClock } from './geo';
import { PRESET_SCENARIOS } from './scenarios';
import { runScenario, seaStateFromWind } from './sim';

vi.setConfig({ testTimeout: 60_000 });

const WHEN = '2026-11-06T09:00:00.000Z';
const preset = (id: string) => PRESET_SCENARIOS.find((p) => p.id === id)!;
const brief = (id: string) => {
  const s = preset(id);
  return { scenario: s, brief: buildBrief(s, runScenario(s), WHEN) };
};

describe('the brief a storyboard makes', () => {
  it('opens on the exercise and closes on what it cannot tell you', () => {
    const { brief: b } = brief('salvo-defense');
    expect(b.classification).toBe(CLASSIFICATION);
    expect(b.preparedAt).toBe(WHEN);
    expect(b.slides[0].kind).toBe('title');
    expect(b.slides[0].title).toBe(preset('salvo-defense').name);
    expect(b.slides.map((s) => s.title)).toEqual(expect.arrayContaining(['Purpose', 'Situation — order of battle', 'Conditions', 'Outcome', 'Assumptions and limitations']));
    expect(b.slides.at(-1)!.title).toBe('Assumptions and limitations');
  });

  it('gives every storyboard moment a slide, in order, with its picture and words', () => {
    const { scenario, brief: b } = brief('salvo-defense');
    const moments = scenario.storyboard!;
    const slides = b.slides.filter((s) => s.kind === 'moment');
    expect(slides).toHaveLength(moments.length);
    expect(slides.map((s) => s.atS)).toEqual(moments.map((m) => m.atS));
    expect(slides.map((s) => s.title)).toEqual(moments.map((m) => m.title));
    expect(slides.every((s) => s.image)).toBe(true);
    expect(slides[0].caption).toBe(moments[0].caption);
    // The sequence slide lists the same beats at the same times, so a reader knows what is coming.
    const sequence = b.slides.find((s) => s.title === 'Execution — sequence of events')!;
    expect(sequence.bullets).toHaveLength(moments.length);
    expect(sequence.bullets![0]).toContain(`T+${formatClock(moments[0].atS)}`);
  });

  it('reads the weather off the scenario and the sea state off the wind', () => {
    const { scenario, brief: b } = brief('sub-ambush');
    const rows = Object.fromEntries(b.slides.find((s) => s.title === 'Conditions')!.rows!);
    const env = scenario.environment;
    expect(rows.Wind).toBe(`${env.windKt} kt from ${Math.round(env.windFromDeg).toString().padStart(3, '0')}°T`);
    expect(rows.Current).toBe(`${env.currentKt} kt toward ${Math.round(env.currentToDeg).toString().padStart(3, '0')}°T`);
    expect(rows['Sea state']).toContain(`${seaStateFromWind(env.windKt)}`);
    expect(rows.Light).toBe(scenario.lightPreset);
    expect(rows['Sensors and detection modelled']).toBe('yes');
  });

  it('counts the outcome off the run, naming what was lost', () => {
    const { scenario, brief: b } = brief('salvo-defense');
    const trajectory = runScenario(scenario);
    const out = outcomeOf(scenario, trajectory);
    const events = trajectory.events;
    expect(out.hits).toBe(events.filter((e) => e.type === 'hit' || e.type === 'mine').length);
    expect(out.intercepts).toBe(events.filter((e) => e.type === 'intercept').length);
    const rows = Object.fromEntries(b.slides.find((s) => s.title === 'Outcome')!.rows!);
    expect(rows['Hits on ships and aircraft']).toBe(`${out.hits}`);
    expect(rows['Weapons shot down']).toBe(`${out.intercepts}`);
    expect(rows['Events in all']).toBe(`${events.length}`);
    // Weapons are not losses: only ships and aircraft are named.
    const named = [...out.blueLost, ...out.redLost];
    for (const who of named) expect(scenario.units.some((u) => u.name === who)).toBe(true);
  });

  it('counts the order of battle by side and class', () => {
    const { scenario, brief: b } = brief('air-raid');
    const bullets = b.slides.find((s) => s.title === 'Situation — order of battle')!.bullets!;
    const blue = bullets.find((x) => x.startsWith('Blue:'))!;
    const fighters = scenario.units.filter((u) => u.classId === 'FIGHTER').length;
    expect(bullets.find((x) => x.startsWith('Opposing force:'))).toContain(`${fighters} × `);
    expect(blue).toContain('×');
  });

  it('says which way the limits run when sensors are off', () => {
    const off = brief('salvo-defense').brief.slides.at(-1)!.bullets!.join(' ');
    const on = brief('sub-ambush').brief.slides.at(-1)!.bullets!.join(' ');
    expect(off).toContain('Sensors and detection are switched off');
    expect(on).toContain('Detection is deterministic');
    for (const text of [off, on]) {
      expect(text).toContain('illustrative figures, not operational data');
      expect(text).toContain('Not navigational guidance');
    }
  });

  it('makes the same deck from the same run', () => {
    const s = preset('minefield-transit');
    const t = runScenario(s);
    expect(buildBrief(s, t, WHEN)).toEqual(buildBrief(s, t, WHEN));
  });

  it('still builds for a scenario with no storyboard', () => {
    const s = { ...preset('air-raid'), storyboard: undefined };
    const b = buildBrief(s, runScenario(s), WHEN);
    expect(b.slides.some((x) => x.kind === 'moment')).toBe(false);
    expect(b.slides.some((x) => x.title === 'Execution — sequence of events')).toBe(false);
    expect(b.slides.at(-1)!.title).toBe('Assumptions and limitations');
  });
});
