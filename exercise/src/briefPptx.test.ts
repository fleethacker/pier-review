import { describe, expect, it, vi } from 'vitest';
import { briefFilename, buildBrief } from './brief';
import type { Brief } from './brief';
import { briefBlob, briefDeck, briefSlideCount, withEmbeddedImages } from './briefPptx';
import { PRESET_SCENARIOS } from './scenarios';
import { runScenario } from './sim';

vi.setConfig({ testTimeout: 120_000 });

const WHEN = '2026-11-06T09:00:00.000Z';
const briefFor = (id: string): Brief => {
  const s = PRESET_SCENARIOS.find((p) => p.id === id)!;
  return buildBrief(s, runScenario(s), WHEN);
};

/**
 * The deck written as a file, for the checks that care what actually comes out. Pictures are embedded first, exactly as
 * the browser does it: in node there is nothing to fetch them from, so they fall away and the slides keep their
 * placeholders — which is the behaviour worth having when an asset cannot be read.
 */
const written = async (brief: Brief): Promise<Buffer> =>
  Buffer.from((await briefDeck(await withEmbeddedImages(brief)).write({ outputType: 'nodebuffer' })) as ArrayBuffer);

describe('the brief as a PowerPoint file', () => {
  it('gives every slide of the brief a slide in the deck, carrying long lists over', () => {
    const brief = briefFor('salvo-defense');
    // One slide each, except a bullet list longer than a slide holds, which continues onto the next.
    const plain = brief.slides.filter((s) => s.kind !== 'bullets').length;
    const listed = brief.slides.filter((s) => s.kind === 'bullets').reduce((n, s) => n + Math.max(1, Math.ceil((s.bullets ?? []).length / 12)), 0);
    expect(briefSlideCount(brief)).toBe(plain + listed);
    expect(briefSlideCount(brief)).toBeGreaterThan(brief.slides.filter((s) => s.kind === 'moment').length);
  });

  it('carries a long list onto a continuation slide', () => {
    const brief = briefFor('salvo-defense');
    const long: Brief = { ...brief, slides: [{ kind: 'bullets', title: 'Long', bullets: Array.from({ length: 25 }, (_, i) => `point ${i + 1}`) }] };
    expect(briefSlideCount(long)).toBe(3);
  });

  it('writes a real PowerPoint file, with the slides inside it', async () => {
    const file = await written(briefFor('salvo-defense'));
    expect(file.length).toBeGreaterThan(5000);
    // A .pptx is a zip; the part names are stored uncompressed in its directory, so they can be read straight out.
    expect(file.subarray(0, 2).toString('latin1')).toBe('PK');
    const text = file.toString('latin1');
    for (const part of ['[Content_Types].xml', 'ppt/presentation.xml', 'ppt/slides/slide1.xml']) {
      expect(text, `missing ${part}`).toContain(part);
    }
  });

  it('marks the deck as an exercise, on the slides themselves', async () => {
    const brief = briefFor('salvo-defense');
    // The file is UTF-8, so read it that way: the marking has an em dash in it.
    const text = (await written(brief)).toString('utf8');
    expect(brief.classification).toContain('EXERCISE');
    const marks = text.split(brief.classification).length - 1;
    expect(marks).toBeGreaterThanOrEqual(briefSlideCount(brief));
  });

  it('names the file for the exercise and the day it was prepared', () => {
    expect(briefFilename(briefFor('salvo-defense'), 'pptx')).toBe('brief-missile-salvo-on-a-carrier-group-20261106.pptx');
    expect(briefFilename({ ...briefFor('salvo-defense'), name: '  ' }, 'pptx')).toMatch(/^brief-exercise-\d{8}\.pptx$/);
    expect(briefFilename(briefFor('air-raid'), 'html')).toMatch(/^brief-air-raid-and-sam-defence-\d{8}\.html$/);
  });

  it('builds a moment with no picture rather than failing on it', async () => {
    const brief = briefFor('salvo-defense');
    const bare: Brief = { ...brief, slides: brief.slides.map((s) => (s.kind === 'moment' ? { ...s, image: undefined } : s)) };
    const file = await written(bare);
    expect(file.subarray(0, 2).toString('latin1')).toBe('PK');
    expect(briefSlideCount(bare)).toBe(briefSlideCount(brief));
    expect(file.toString('latin1')).toContain('No picture');
  });

  it('drops a picture it cannot fetch instead of losing the whole file', async () => {
    const brief = briefFor('salvo-defense');
    const resolved = await withEmbeddedImages({ ...brief, slides: brief.slides.map((s) => (s.kind === 'moment' ? { ...s, image: 'https://example.invalid/missing.jpg' } : s)) });
    expect(resolved.slides.filter((s) => s.kind === 'moment').every((s) => s.image === undefined)).toBe(true);
    expect(resolved.slides.filter((s) => s.kind === 'moment').length).toBeGreaterThan(0);
  });

  it('keeps a picture that is already inline', async () => {
    const inline = 'data:image/png;base64,iVBORw0KGgo=';
    const brief = briefFor('salvo-defense');
    const resolved = await withEmbeddedImages({ ...brief, slides: brief.slides.map((s) => (s.kind === 'moment' ? { ...s, image: inline } : s)) });
    expect(resolved.slides.find((s) => s.kind === 'moment')!.image).toBe(inline);
  });

  it('hands the browser a file to save', async () => {
    const blob = await briefBlob(briefFor('air-raid'));
    expect(blob.size).toBeGreaterThan(5000);
  });
});
