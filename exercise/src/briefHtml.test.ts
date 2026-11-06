import { describe, expect, it, vi } from 'vitest';
import { buildBrief } from './brief';
import type { Brief } from './brief';
import { briefHtml } from './briefHtml';
import { briefSlideCount } from './briefPptx';
import { formatClock } from './geo';
import { PRESET_SCENARIOS } from './scenarios';
import { runScenario } from './sim';

vi.setConfig({ testTimeout: 60_000 });

const WHEN = '2026-11-06T09:00:00.000Z';
const briefFor = (id: string): Brief => {
  const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
  return buildBrief(s, runScenario(s), WHEN);
};
const slides = (html: string) => html.split('<section class="slide').length - 1;

describe('the brief as a page of slides', () => {
  it('draws one slide per slide of the brief, the same count as the PowerPoint', () => {
    const brief = briefFor('salvo-defense');
    expect(slides(briefHtml(brief))).toBe(briefSlideCount(brief));
  });

  it('gives each slide the marking, the exercise and its number', () => {
    const brief = briefFor('salvo-defense');
    const html = briefHtml(brief);
    const total = briefSlideCount(brief);
    // Top and bottom of every slide.
    expect(html.split(brief.classification).length - 1).toBe(total * 2);
    expect(html).toContain(`1 / ${total}`);
    expect(html).toContain(`${total} / ${total}`);
  });

  it('carries the storyboard: every moment with its time, picture and caption', () => {
    const scenario = PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
    const html = briefHtml(briefFor('salvo-defense'));
    for (const m of scenario.storyboard!) {
      expect(html).toContain(`T+${formatClock(m.atS)}`);
      if (m.image) expect(html).toContain(`src="${m.image}"`);
      if (m.caption) expect(html).toContain(m.caption.replace(/&/g, '&amp;'));
    }
  });

  it('prints as landscape pages, one slide to a page', () => {
    const html = briefHtml(briefFor('air-raid'));
    expect(html).toContain('@page { size: 13.333in 7.5in');
    expect(html).toContain('page-break-after:always');
    expect(html).toContain('width:13.333in; height:7.5in');
  });

  it('shows the weather and the outcome as tables', () => {
    const html = briefHtml(briefFor('sub-ambush'));
    expect(html).toContain('<th>Item</th>');
    expect(html).toContain('<th>Result</th>');
    expect(html).toContain('Sea state');
    expect(html).toContain('Weapons shot down');
  });

  it('escapes what it is given, so a scenario name cannot inject markup', () => {
    const brief = { ...briefFor('air-raid'), name: '<script>alert(1)</script>' };
    const html = briefHtml(brief);
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('puts a placeholder where a moment has no picture', () => {
    const brief = briefFor('salvo-defense');
    const bare = { ...brief, slides: brief.slides.map((s) => (s.kind === 'moment' ? { ...s, image: undefined } : s)) };
    expect(briefHtml(bare)).toContain('No picture');
    expect(slides(briefHtml(bare))).toBe(briefSlideCount(brief));
  });
});
