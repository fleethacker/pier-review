// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { storyboardHtml } from './exportResults';
import { exportScenario, parseScenario } from './scenarioJson';
import { PRESET_SCENARIOS } from './scenarios';
import { runScenario } from './sim';
import { STOCK, pickStock, stockByUrl, isStock } from './stockImages';
import {
  autoStoryboard,
  createBubble,
  defaultHoldS,
  imageBytes,
  inOrder,
  momentAnchor,
  momentsAt,
  nextMomentId,
  readImageFile,
  validateStoryboard,
  MIN_HOLD_S,
} from './storyboard';
import type { Environment, ScenarioConfig, StoryMoment, UnitConfig } from './types';

vi.setConfig({ testTimeout: 60_000 });

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
  description: 'A first sentence. A second sentence. A third one nobody reads.',
  center: C,
  durationS: 600,
  lightPreset: 'day',
  environment: still,
  units,
  ...patch,
});
const beat = (patch: Partial<StoryMoment> & Pick<StoryMoment, 'id' | 'atS'>): StoryMoment => ({ holdS: 100, title: patch.id, ...patch });

describe('which moments are up', () => {
  const moments = [beat({ id: 'a', atS: 0, holdS: 100, unitId: 'u1' }), beat({ id: 'b', atS: 200, holdS: 100, unitId: 'u1' }), beat({ id: 'c', atS: 50, holdS: 100, unitId: 'u2' })];

  it('shows a moment only inside its window', () => {
    expect(momentsAt(moments, 10).map((a) => a.moment.id)).toEqual(['a']);
    expect(momentsAt(moments, 60).map((a) => a.moment.id).sort()).toEqual(['a', 'c']);
    expect(momentsAt(moments, 160)).toEqual([]);
    expect(momentsAt(moments, 250).map((a) => a.moment.id)).toEqual(['b']);
  });

  it('lets a later moment replace an earlier one on the same unit, and keeps other units alongside', () => {
    const overlapping = [beat({ id: 'first', atS: 0, holdS: 300, unitId: 'u1' }), beat({ id: 'second', atS: 100, holdS: 300, unitId: 'u1' }), beat({ id: 'other', atS: 100, holdS: 300, unitId: 'u2' })];
    expect(momentsAt(overlapping, 150).map((a) => a.moment.id).sort()).toEqual(['other', 'second']);
  });

  it('keeps two moments with no unit apart from each other', () => {
    const floating = [beat({ id: 'x', atS: 0, holdS: 300 }), beat({ id: 'y', atS: 10, holdS: 300 })];
    expect(momentsAt(floating, 50)).toHaveLength(2);
  });

  it('fades in as it arrives and out as it leaves, full in the middle', () => {
    const one = [beat({ id: 'a', atS: 0, holdS: 100 })];
    const at = (t: number) => momentsAt(one, t)[0].opacity;
    expect(at(0)).toBe(0);
    expect(at(50)).toBe(1);
    expect(at(99.5)).toBeLessThan(0.1);
    expect(at(4)).toBeLessThan(at(8));
    expect(at(99)).toBeLessThan(at(90));
  });

  it('treats a hold below the floor as the floor, so a moment is never up for no time at all', () => {
    expect(momentsAt([beat({ id: 'a', atS: 0, holdS: 0 })], MIN_HOLD_S - 1)).toHaveLength(1);
  });

  it('scales the default hold with the length of the scenario, within reason', () => {
    expect(defaultHoldS(600)).toBe(50);
    expect(defaultHoldS(60)).toBe(45);
    expect(defaultHoldS(100_000)).toBe(420);
  });
});

describe('where a bubble hangs', () => {
  const s = scenario([unit({ id: 'u1', speedKt: 20, behavior: { type: 'route', waypoints: [{ lon: -61, lat: 33 }] } })]);
  const traj = runScenario(s);

  it('follows its unit as the unit moves', () => {
    const early = momentAnchor(s, traj, beat({ id: 'a', atS: 0, unitId: 'u1' }), 0)!;
    const later = momentAnchor(s, traj, beat({ id: 'a', atS: 0, unitId: 'u1' }), 500)!;
    expect(later.lon).toBeGreaterThan(early.lon);
  });

  it('sits where it was told to, or at the center, when it hangs on nothing', () => {
    expect(momentAnchor(s, traj, beat({ id: 'a', atS: 0, at: { lon: 1, lat: 2 } }), 0)).toEqual({ lon: 1, lat: 2 });
    expect(momentAnchor(s, traj, beat({ id: 'a', atS: 0 }), 0)).toEqual(C);
  });

  it('falls back to its own spot when the unit is gone from the run', () => {
    expect(momentAnchor(s, traj, beat({ id: 'a', atS: 0, unitId: 'ghost', at: { lon: 5, lat: 6 } }), 0)).toEqual({ lon: 5, lat: 6 });
    expect(momentAnchor(s, traj, beat({ id: 'a', atS: 0, unitId: 'ghost' }), 0)).toBeNull();
  });
});

describe('building a storyboard from the run', () => {
  const s = PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
  const traj = runScenario(s);

  it('opens by naming the exercise, then follows the run in order', () => {
    const made = autoStoryboard(s, traj);
    expect(made[0]).toMatchObject({ atS: 0, title: s.name, at: s.center });
    expect(made[0].caption).toBe('A hostile destroyer fires eight anti-ship missiles at the carrier and two aircraft fire at the cruiser. The escorts shoot what they can');
    expect(made.map((m) => m.atS)).toEqual([...made.map((m) => m.atS)].sort((a, b) => a - b));
    expect(new Set(made.map((m) => m.id)).size).toBe(made.length);
    expect(validateStoryboard(s, made)).toEqual([]);
  });

  it('keeps the moments worth telling and leaves the rest', () => {
    const made = autoStoryboard(s, traj, { max: 8 });
    expect(made).toHaveLength(9); // the opening plus eight
    const titles = made.map((m) => m.title).join(' | ');
    expect(titles).toMatch(/Hit|Lost/);
    // The carrier being hit beats a routine launch when there is only room for a few.
    expect(titles).toContain('Carrier 1');
  });

  it('hangs beats on ships and aircraft, not on the missiles that are gone a moment later', () => {
    const made = autoStoryboard(s, traj, { max: 10 }).filter((m) => m.unitId);
    const weapons = made.filter((m) => ['ASM', 'SAM', 'TORP', 'MINE', 'DRONE'].includes(s.units.find((u) => u.id === m.unitId)!.classId));
    expect(weapons).toHaveLength(0);
  });

  it('spreads the beats so one unit does not take them all', () => {
    const made = autoStoryboard(s, traj, { max: 12, minGapS: 400 });
    const perUnit = new Map<string, number>();
    for (const m of made.filter((x) => x.unitId)) perUnit.set(m.unitId!, (perUnit.get(m.unitId!) ?? 0) + 1);
    expect(Math.max(...perUnit.values())).toBeLessThanOrEqual(Math.ceil(s.durationS / 400) + 1);
  });

  it('can skip the opening, and puts a picture on every beat when given one', () => {
    const made = autoStoryboard(s, traj, { noOpening: true, max: 5, picture: () => 'pic.jpg' });
    expect(made.every((m) => m.image === 'pic.jpg')).toBe(true);
    expect(made.some((m) => m.title === s.name)).toBe(false);
  });

  it('makes a storyboard for a run where nothing happens', () => {
    const quiet = scenario([unit({ id: 'u1' })]);
    const made = autoStoryboard(quiet, runScenario(quiet));
    expect(made).toHaveLength(1);
    expect(made[0].title).toBe('Test exercise');
  });
});

describe('housekeeping', () => {
  it('finds a free id, counts picture bytes and orders beats by time', () => {
    expect(nextMomentId([])).toBe('story-1');
    expect(nextMomentId([beat({ id: 'story-1', atS: 0 }), beat({ id: 'story-2', atS: 0 })])).toBe('story-3');
    expect(imageBytes([beat({ id: 'a', atS: 0 })])).toBe(0);
    expect(imageBytes([beat({ id: 'a', atS: 0, image: 'x'.repeat(4000) })])).toBe(3000);
    expect(inOrder([beat({ id: 'b', atS: 90 }), beat({ id: 'a', atS: 10 })]).map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('reports what is wrong with a storyboard', () => {
    const s = scenario([unit({ id: 'u1' })]);
    const problems = validateStoryboard(s, [
      beat({ id: 'dup', atS: 0 }),
      beat({ id: 'dup', atS: -5 }),
      beat({ id: 'short', atS: 0, holdS: 1 }),
      beat({ id: 'ghost', atS: 0, unitId: 'nope' }),
    ]);
    expect(problems.some((p) => /share the id/.test(p))).toBe(true);
    expect(problems.some((p) => /zero or more/.test(p))).toBe(true);
    expect(problems.some((p) => /at least/.test(p))).toBe(true);
    expect(problems.some((p) => /does not exist/.test(p))).toBe(true);
    expect(validateStoryboard(s, [beat({ id: 'ok', atS: 0, unitId: 'u1' })])).toEqual([]);
  });
});

describe('the bubble on the map', () => {
  it('shows the picture, the title and the caption, and says what it is', () => {
    const el = createBubble(beat({ id: 'a', atS: 0, title: 'Carrier 1 — hit', caption: 'One got through.', image: 'p.jpg' }), { color: '#3da5ff' });
    expect(el.getAttribute('aria-label')).toBe('Storyboard: Carrier 1 — hit');
    expect(el.querySelector('img')!.getAttribute('src')).toBe('p.jpg');
    expect(el.textContent).toContain('Carrier 1 — hit');
    expect(el.textContent).toContain('One got through.');
    expect(el.style.borderColor || el.style.border).toBeTruthy();
  });

  it('leaves out the picture and the caption when a beat has none', () => {
    const el = createBubble(beat({ id: 'a', atS: 0, title: 'Just words' }), { color: '#fff' });
    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toBe('Just words');
  });

  it('drops a picture that will not load rather than leaving a broken frame', () => {
    const el = createBubble(beat({ id: 'a', atS: 0, title: 't', image: 'gone.jpg' }), { color: '#fff' });
    const img = el.querySelector('img')!;
    img.onerror!(new Event('error'));
    expect(el.querySelector('img')).toBeNull();
  });

  it('calls back when clicked, without the click reaching the map underneath', () => {
    const onClick = vi.fn();
    const el = createBubble(beat({ id: 'a', atS: 0, title: 't' }), { color: '#fff', onClick });
    const outer = vi.fn();
    document.body.appendChild(el);
    document.body.addEventListener('click', outer);
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onClick).toHaveBeenCalled();
    expect(outer).not.toHaveBeenCalled();
    document.body.removeEventListener('click', outer);
    el.remove();
  });
});

describe('pictures from files', () => {
  const file = (type = 'image/png', size = 100) => ({ name: 'shot.png', type, size }) as File;

  it('refuses what is not a picture, and what is far too big', async () => {
    await expect(readImageFile(file('application/pdf'))).rejects.toThrow(/not a picture/);
    await expect(readImageFile(file('image/png', 9_000_000))).rejects.toThrow(/too big/);
  });
});

describe('the stock pictures', () => {
  it('are all public domain, with a source, and each has its own id and file', () => {
    expect(STOCK.length).toBeGreaterThanOrEqual(10);
    expect(new Set(STOCK.map((s) => s.id)).size).toBe(STOCK.length);
    expect(new Set(STOCK.map((s) => s.url)).size).toBe(STOCK.length);
    for (const s of STOCK) {
      expect(s.source.license.toLowerCase(), s.id).toContain('public domain');
      expect(s.source.page, s.id).toMatch(/^https:\/\/commons\.wikimedia\.org\//);
      expect(s.label.length, s.id).toBeGreaterThan(3);
    }
  });

  it('picks one that fits the event first, then the unit', () => {
    expect(pickStock('destroyed', 'CVN')!.id).toBe('burning');
    expect(pickStock(undefined, 'SSN')!.id).toBe('submarine');
    expect(pickStock(undefined, 'HELO')!.id).toBe('helo');
    expect(pickStock('launch', 'UAV')!.id).toBe('uav');
    expect(pickStock(undefined, undefined)).toBeUndefined();
  });

  it('knows its own pictures from captured ones', () => {
    expect(isStock(STOCK[0].url)).toBe(true);
    expect(isStock('data:image/jpeg;base64,abc')).toBe(false);
    expect(isStock(undefined)).toBe(false);
    expect(stockByUrl(STOCK[2].url)!.id).toBe(STOCK[2].id);
  });
});

describe('the storyboard in a scenario file', () => {
  it('rides along with the scenario, through a save and a load', () => {
    const s = scenario([unit({ id: 'u1' })], {
      storyboard: [beat({ id: 'a', atS: 10, holdS: 60, unitId: 'u1', title: 'Away', caption: 'Off she goes', image: 'data:image/jpeg;base64,abc' }), beat({ id: 'b', atS: 30, at: { lon: 1, lat: 2 }, title: 'Elsewhere' })],
    });
    const back = parseScenario(exportScenario(s));
    expect(back.storyboard).toEqual(s.storyboard);
  });

  it('is left out when there is none, and a broken one is caught on load', () => {
    expect(parseScenario(exportScenario(scenario([unit({ id: 'u1' })]))).storyboard).toBeUndefined();
    const bad = JSON.stringify({ ...scenario([unit({ id: 'u1' })]), storyboard: [{ id: 'a', atS: 0, holdS: 60, title: 't', unitId: 'ghost' }] });
    expect(() => parseScenario(bad)).toThrow(/does not exist/);
    const malformed = JSON.stringify({ ...scenario([unit({ id: 'u1' })]), storyboard: [{ atS: 0 }] });
    expect(() => parseScenario(malformed)).toThrow(/storyboard\[0\]\.id/);
  });

  it('ships with the salvo preset, in order, with a picture on every moment', () => {
    const s = PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!;
    const moments = s.storyboard!;
    expect(moments.length).toBeGreaterThanOrEqual(8);
    expect(validateStoryboard(s, moments)).toEqual([]);
    expect(moments.every((m) => m.image)).toBe(true);
    expect(moments.map((m) => m.atS)).toEqual([...moments.map((m) => m.atS)].sort((a, b) => a - b));
    expect(moments.every((m) => m.atS <= s.durationS)).toBe(true);
    // The beat about the carrier being hit lands when the carrier is actually hit.
    const hit = runScenario(s).events.find((e) => e.type === 'hit' && e.otherId === 'cvn1')!;
    const beatAboutIt = moments.find((m) => /hit/i.test(m.title))!;
    expect(Math.abs(beatAboutIt.atS - hit.tS)).toBeLessThan(30);
  });
});

describe('the storyboard as a page to print', () => {
  it('lays every moment out in order with its picture and words, and escapes what it is given', () => {
    const s = scenario([unit({ id: 'u1', name: 'Ship <one>' })], {
      name: 'Exercise <sharp>',
      storyboard: [beat({ id: 'b', atS: 90, title: 'Second' }), beat({ id: 'a', atS: 10, unitId: 'u1', title: 'First & best', caption: 'A caption', image: 'p.jpg' })],
    });
    const html = storyboardHtml(s);
    expect(html.indexOf('First &amp; best')).toBeLessThan(html.indexOf('Second'));
    expect(html).toContain('Exercise &lt;sharp&gt;');
    expect(html).not.toContain('<sharp>');
    expect(html).toContain('Ship &lt;one&gt;');
    expect(html).toContain('src="p.jpg"');
    expect(html).toContain('No picture');
    expect(html).toContain('2 moments');
  });

  it('says so when there is no storyboard at all', () => {
    expect(storyboardHtml(scenario([unit({ id: 'u1' })]))).toContain('no storyboard yet');
  });
});
