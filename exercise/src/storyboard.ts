import { formatClock } from './geo';
import { SHIP_CLASSES, isPlatform } from './ships';
import type { EventType, SimEvent, Trajectory } from './sim';
import { unitStateAt } from './sim';
import { eventFocus, eventText } from './status';
import type { LonLat, ScenarioConfig, StoryMoment } from './types';

/**
 * The storyboard: pictures and captions pinned to a time and a unit, which come up in a bubble beside that unit while the
 * run plays and go again when their time is up. This file is the part that does not touch the map or React: which beats are
 * up at a given moment, how to build a set from what happened in the run, and how big the pictures are.
 */

export const MIN_HOLD_S = 5;
export const MAX_MOMENTS = 200;
/** Fraction of a beat's hold spent fading in and out, and the shortest fade in seconds of run time. */
const FADE_IN = 0.08;
const FADE_OUT = 0.16;
const MIN_FADE_S = 1;

/** A sensible hold for a scenario of this length: long enough to read at the speeds people watch at. */
export function defaultHoldS(durationS: number): number {
  return Math.round(Math.min(420, Math.max(45, durationS / 12)));
}

export interface ActiveMoment {
  moment: StoryMoment;
  /** 0 at the start of the beat, 1 at the end. */
  progress: number;
  /** Fades up as it arrives and down as it leaves, so beats do not snap on and off. */
  opacity: number;
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

/**
 * The beats up at `timeS`, newest first per unit. A unit shows only its latest beat, so a later one replaces an earlier one
 * that is still within its hold rather than stacking on top of it.
 */
export function momentsAt(moments: StoryMoment[], timeS: number): ActiveMoment[] {
  const live: ActiveMoment[] = [];
  for (const m of moments) {
    const hold = Math.max(MIN_HOLD_S, m.holdS);
    const age = timeS - m.atS;
    if (age < 0 || age > hold) continue;
    const progress = age / hold;
    const fadeIn = Math.max(MIN_FADE_S, hold * FADE_IN);
    const fadeOut = Math.max(MIN_FADE_S, hold * FADE_OUT);
    const opacity = clamp01(Math.min(age / fadeIn, (hold - age) / fadeOut));
    live.push({ moment: m, progress, opacity });
  }
  // One bubble per anchor: the beat that started most recently wins.
  const byAnchor = new Map<string, ActiveMoment>();
  for (const a of live) {
    const key = a.moment.unitId ?? `@${a.moment.id}`;
    const held = byAnchor.get(key);
    if (!held || a.moment.atS >= held.moment.atS) byAnchor.set(key, a);
  }
  return [...byAnchor.values()].sort((a, b) => a.moment.atS - b.moment.atS);
}

/** Where a beat's bubble hangs at `timeS`: on its unit if it has one, else at its own spot or the scenario's center. */
export function momentAnchor(scenario: ScenarioConfig, trajectory: Trajectory, m: StoryMoment, timeS: number): LonLat | null {
  if (m.unitId) {
    const i = trajectory.unitIds.indexOf(m.unitId);
    if (i < 0) return m.at ?? null;
    const st = unitStateAt(trajectory, i, timeS);
    // A spent missile or a sunk aircraft is gone from the map: keep the bubble where it was last seen.
    return { lon: st.lon, lat: st.lat };
  }
  return m.at ?? scenario.center;
}

// ---- building a storyboard from what happened ----

/** How much each kind of event is worth telling: the storyboard keeps the best ones when there are more than it can show. */
const WORTH: Partial<Record<EventType, number>> = {
  destroyed: 6,
  mine: 5,
  hit: 4,
  intercept: 2,
  detected: 1.5,
  held: 1.2,
  launch: 1,
  aborted: 1,
};

const TITLE: Partial<Record<EventType, string>> = {
  destroyed: 'Lost',
  mine: 'Mine strike',
  hit: 'Hit',
  intercept: 'Shot down',
  detected: 'Contact',
  held: 'Shot held',
  launch: 'Launch',
  aborted: 'Launch aborted',
};

export interface AutoOptions {
  /** Most beats to make. */
  max?: number;
  holdS?: number;
  /** Two beats on the same unit are kept this far apart, seconds. */
  minGapS?: number;
  /** Leave out the opening beat that names the exercise. */
  noOpening?: boolean;
  /** Supplies a picture for a beat. Left out, the beats come with no pictures. */
  picture?: (event: EventType | undefined, unitId: string | undefined) => string | undefined;
}

/**
 * Build a storyboard from the run: an opening beat, then the moments worth a picture, spread over the units so no one ship
 * hogs the screen. Pictures are left empty; capture them on the map, or load them from the slides you already have.
 */
export function autoStoryboard(scenario: ScenarioConfig, trajectory: Trajectory, options: AutoOptions = {}): StoryMoment[] {
  const max = Math.max(1, Math.min(MAX_MOMENTS, options.max ?? 14));
  const holdS = Math.max(MIN_HOLD_S, options.holdS ?? defaultHoldS(scenario.durationS));
  const minGapS = options.minGapS ?? Math.max(holdS * 0.75, scenario.durationS / 30);
  const name = (id: string) => scenario.units.find((u) => u.id === id)?.name ?? id;

  const opening: StoryMoment[] = options.noOpening
    ? []
    : [
        {
          id: 'story-open',
          atS: 0,
          holdS,
          title: scenario.name,
          caption: scenario.description.split('. ').slice(0, 2).join('. ').trim() || undefined,
          at: scenario.center,
          image: options.picture?.(undefined, undefined),
        },
      ];

  interface Candidate {
    event: SimEvent;
    anchor: string | undefined;
    worth: number;
  }
  const candidates: Candidate[] = [];
  for (const e of trajectory.events) {
    const worth = WORTH[e.type];
    if (worth === undefined) continue;
    const anchor = eventFocus(e, scenario.units);
    // A ship or aircraft carries the beat; a missile's own bubble would be gone before it could be read.
    const cls = anchor ? SHIP_CLASSES[scenario.units.find((u) => u.id === anchor)!.classId] : undefined;
    candidates.push({ event: e, anchor, worth: worth + (cls && isPlatform(cls) ? 0.5 : 0) });
  }
  candidates.sort((a, b) => b.worth - a.worth || a.event.tS - b.event.tS);

  const takenByAnchor = new Map<string, number[]>();
  const kept: Candidate[] = [];
  for (const c of candidates) {
    if (kept.length >= max) break;
    const key = c.anchor ?? '@floating';
    const times = takenByAnchor.get(key) ?? [];
    if (times.some((t) => Math.abs(t - c.event.tS) < minGapS)) continue;
    times.push(c.event.tS);
    takenByAnchor.set(key, times);
    kept.push(c);
  }
  kept.sort((a, b) => a.event.tS - b.event.tS);

  return [
    ...opening,
    ...kept.map(({ event, anchor }, i): StoryMoment => {
      const who = anchor ? name(anchor) : name(event.unitId);
      return {
        id: `story-${i + 1}`,
        unitId: anchor,
        at: anchor ? undefined : { lon: event.lon, lat: event.lat },
        atS: event.tS,
        holdS,
        title: `${who} — ${TITLE[event.type] ?? event.type}`,
        caption: `T+${formatClock(event.tS)}  ${eventText(event, name)}`,
        image: options.picture?.(event.type, anchor ?? event.unitId),
      };
    }),
  ];
}

// ---- housekeeping ----

export function nextMomentId(moments: StoryMoment[]): string {
  let n = moments.length + 1;
  const taken = new Set(moments.map((m) => m.id));
  while (taken.has(`story-${n}`)) n++;
  return `story-${n}`;
}

/** Roughly how many bytes the pictures add to the scenario file. Data URIs are base64, so about 3 bytes per 4 characters. */
export function imageBytes(moments: StoryMoment[]): number {
  return moments.reduce((sum, m) => sum + (m.image ? Math.round(m.image.length * 0.75) : 0), 0);
}

export function validateStoryboard(scenario: ScenarioConfig, moments: StoryMoment[]): string[] {
  const errors: string[] = [];
  if (moments.length > MAX_MOMENTS) errors.push(`A storyboard can hold at most ${MAX_MOMENTS} moments.`);
  const seen = new Set<string>();
  for (const m of moments) {
    const what = `Moment "${m.title || m.id}"`;
    if (seen.has(m.id)) errors.push(`Two moments share the id "${m.id}".`);
    seen.add(m.id);
    if (!Number.isFinite(m.atS) || m.atS < 0) errors.push(`${what}: the time must be zero or more.`);
    if (!(m.holdS >= MIN_HOLD_S)) errors.push(`${what}: it must stay up for at least ${MIN_HOLD_S} seconds.`);
    if (m.unitId && !scenario.units.some((u) => u.id === m.unitId)) errors.push(`${what}: it hangs on a unit that does not exist, "${m.unitId}".`);
  }
  return errors;
}

/** Order the beats as a reader would go through them. */
export const inOrder = (moments: StoryMoment[]): StoryMoment[] => [...moments].sort((a, b) => a.atS - b.atS || a.id.localeCompare(b.id));

// ---- the bubble on the map ----

const PANEL = '#0d1f3c';
const TEXT = '#8ba4c4';

export interface BubbleOptions {
  /** Colour of the side the unit belongs to, for the edge and the title. */
  color: string;
  /** Called when the bubble is clicked, to select the unit and open the beat for editing. */
  onClick?: () => void;
  width?: number;
}

/**
 * Build the bubble that hangs beside a unit: the picture, the title and the caption. Plain DOM, because it rides on a
 * Mapbox marker rather than in the React tree, and inline styles so it does not depend on the stylesheet being loaded.
 */
export function createBubble(moment: StoryMoment, options: BubbleOptions): HTMLElement {
  const width = options.width ?? 212;
  const el = document.createElement('div');
  el.className = 'exercise-story-bubble';
  el.setAttribute('role', 'figure');
  el.setAttribute('aria-label', `Storyboard: ${moment.title}`);
  Object.assign(el.style, {
    width: `${width}px`,
    background: `${PANEL}f2`,
    border: `1px solid ${options.color}99`,
    borderRadius: '10px',
    overflow: 'hidden',
    boxShadow: '0 6px 22px rgba(0,0,0,0.55)',
    backdropFilter: 'blur(3px)',
    cursor: options.onClick ? 'pointer' : 'default',
    transition: 'opacity 120ms linear',
    fontFamily: 'inherit',
  } as Partial<CSSStyleDeclaration>);

  if (moment.image) {
    const img = document.createElement('img');
    img.src = moment.image;
    img.alt = '';
    Object.assign(img.style, { display: 'block', width: '100%', height: `${Math.round(width * 0.62)}px`, objectFit: 'cover' } as Partial<CSSStyleDeclaration>);
    // A picture that will not load must not leave a broken frame on the map.
    img.onerror = () => img.remove();
    el.appendChild(img);
  }

  const body = document.createElement('div');
  Object.assign(body.style, { padding: '7px 9px 8px' } as Partial<CSSStyleDeclaration>);

  const title = document.createElement('div');
  title.textContent = moment.title;
  Object.assign(title.style, {
    color: options.color,
    fontSize: '11px',
    fontWeight: '600',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    lineHeight: '1.3',
  } as Partial<CSSStyleDeclaration>);
  body.appendChild(title);

  if (moment.caption) {
    const caption = document.createElement('div');
    caption.textContent = moment.caption;
    Object.assign(caption.style, { color: TEXT, fontSize: '11px', lineHeight: '1.35', marginTop: '3px' } as Partial<CSSStyleDeclaration>);
    body.appendChild(caption);
  }
  el.appendChild(body);

  // The tail that points down at the unit.
  const tail = document.createElement('div');
  Object.assign(tail.style, {
    width: '10px',
    height: '10px',
    margin: '-6px auto 0',
    background: `${PANEL}f2`,
    borderRight: `1px solid ${options.color}99`,
    borderBottom: `1px solid ${options.color}99`,
    transform: 'rotate(45deg)',
    position: 'relative',
    borderBottomRightRadius: '2px',
  } as Partial<CSSStyleDeclaration>);
  el.appendChild(tail);

  if (options.onClick) {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      options.onClick!();
    });
  }
  return el;
}

/** Bring an element into view where the browser can. Not every environment implements it, and it is never worth an error. */
export function scrollIntoViewSafely(el: Element | null | undefined): void {
  if (el && typeof (el as HTMLElement).scrollIntoView === 'function') (el as HTMLElement).scrollIntoView({ block: 'nearest', inline: 'center' });
}

// ---- pictures from files ----

export const MAX_PICTURE_BYTES = 8_000_000;

/**
 * Read a picture a user chose and shrink it to something a scenario file can carry: at most `maxWidth` across, as a JPEG
 * data URI. Throws a readable error if the file is not a picture this browser can open.
 */
export async function readImageFile(file: File, maxWidth = 520, quality = 0.72): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error(`"${file.name}" is not a picture.`);
  if (file.size > MAX_PICTURE_BYTES) throw new Error(`"${file.name}" is too big. Use a picture under ${Math.round(MAX_PICTURE_BYTES / 1e6)} MB.`);
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`"${file.name}" could not be read.`));
    reader.readAsDataURL(file);
  });
  const img = new Image();
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error(`"${file.name}" is not a picture this browser can open.`));
    img.src = dataUrl;
  });
  const scale = Math.min(1, maxWidth / (img.naturalWidth || maxWidth));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round((img.naturalWidth || maxWidth) * scale));
  canvas.height = Math.max(1, Math.round((img.naturalHeight || maxWidth) * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('This browser would not give a drawing context to shrink the picture in.');
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', quality);
}
