import PptxGenJS from 'pptxgenjs';
import type { Brief, BriefSlide } from './brief';
import { formatClock } from './geo';

/**
 * The brief as a PowerPoint file: a plain staff deck, one idea to a slide, that someone can open and edit. The content
 * is decided in `brief.ts`; this file only lays it out. pptxgenjs is a large library, so load this module when a brief
 * is asked for rather than with the page.
 */

const NAVY = '1F3864';
const TEXT = '202020';
const GREY = '595959';
const WHITE = 'FFFFFF';
const FONT = 'Arial';

/** Slide is 10 × 5.625 inches at 16:9. Everything below is positioned in inches inside that. */
const W = 10;
const BODY_TOP = 1.35;
const BODY_H = 3.5;
const MARGIN = 0.55;
/** Bullets past this many go on a continuation slide, so nothing runs off the bottom. */
const MAX_BULLETS = 12;

type Slide = ReturnType<PptxGenJS['addSlide']>;

/** The marking, the exercise and the slide number, on every slide. */
function frame(slide: Slide, brief: Brief, n: number): void {
  for (const y of [0.08, 5.3]) {
    slide.addText(brief.classification, {
      x: 0, y, w: W, h: 0.22, align: 'center', bold: true, fontSize: 9, color: NAVY, fontFace: FONT,
    });
  }
  slide.addText(brief.name, { x: MARGIN, y: 5.05, w: 6, h: 0.22, fontSize: 8, color: GREY, fontFace: FONT });
  slide.addText(`${n}`, { x: W - MARGIN - 1, y: 5.05, w: 1, h: 0.22, align: 'right', fontSize: 8, color: GREY, fontFace: FONT });
}

/** The heading block: title, an optional line under it, and the rule that separates it from the body. */
function heading(slide: Slide, title: string, subtitle?: string): void {
  slide.addText(title, { x: MARGIN, y: 0.45, w: W - MARGIN * 2, h: 0.45, bold: true, fontSize: 26, color: NAVY, fontFace: FONT });
  slide.addShape('line', { x: MARGIN, y: 0.98, w: W - MARGIN * 2, h: 0, line: { color: NAVY, width: 1.5 } });
  if (subtitle) {
    slide.addText(subtitle, { x: MARGIN, y: 1.0, w: W - MARGIN * 2, h: 0.3, italic: true, fontSize: 12, color: GREY, fontFace: FONT });
  }
}

function titleSlide(slide: Slide, s: BriefSlide): void {
  slide.addText(s.title, { x: MARGIN, y: 1.5, w: W - MARGIN * 2, h: 0.9, align: 'center', bold: true, fontSize: 34, color: NAVY, fontFace: FONT });
  if (s.subtitle) {
    slide.addText(s.subtitle, { x: MARGIN, y: 2.35, w: W - MARGIN * 2, h: 0.35, align: 'center', fontSize: 15, color: GREY, fontFace: FONT });
  }
  const rows = s.rows ?? [];
  rows.forEach(([k, v], i) => {
    const y = 3.0 + i * 0.3;
    slide.addText(`${k}`, { x: 2.6, y, w: 2.3, h: 0.28, align: 'right', bold: true, fontSize: 11, color: GREY, fontFace: FONT });
    slide.addText(`${v}`, { x: 5.05, y, w: 3.2, h: 0.28, fontSize: 11, color: TEXT, fontFace: FONT });
  });
}

function bulletSlide(slide: Slide, title: string, subtitle: string | undefined, bullets: string[]): void {
  heading(slide, title, subtitle);
  slide.addText(
    bullets.map((text) => ({ text, options: { bullet: true, breakLine: true } })),
    { x: MARGIN, y: BODY_TOP, w: W - MARGIN * 2, h: BODY_H, fontSize: 14, color: TEXT, fontFace: FONT, lineSpacingMultiple: 1.2, shrinkText: true, valign: 'top' },
  );
}

function tableSlide(slide: Slide, s: BriefSlide, headers: [string, string]): void {
  heading(slide, s.title, s.subtitle);
  const head = headers.map((text) => ({ text, options: { bold: true, color: WHITE, fill: { color: NAVY } } }));
  const body = (s.rows ?? []).map(([k, v]) => [{ text: k, options: { bold: true } }, { text: v }]);
  slide.addTable([head, ...body], {
    x: MARGIN, y: BODY_TOP, w: W - MARGIN * 2, colW: [3.6, W - MARGIN * 2 - 3.6],
    fontSize: 12, color: TEXT, fontFace: FONT, border: { type: 'solid', color: 'D9D9D9', pt: 1 },
    fill: { color: WHITE }, rowH: 0.3, valign: 'middle',
  });
}

/** A storyboard beat: the picture on the left, the words on the right. */
function momentSlide(slide: Slide, s: BriefSlide): void {
  heading(slide, s.title, undefined);
  const picW = 5.2;
  if (s.image?.startsWith('data:')) {
    // `sizing: contain` keeps the picture's shape; a storyboard picture is never stretched to fit the box.
    slide.addImage({ data: s.image, x: MARGIN, y: BODY_TOP, w: picW, h: BODY_H, sizing: { type: 'contain', w: picW, h: BODY_H } });
  } else {
    slide.addShape('rect', { x: MARGIN, y: BODY_TOP, w: picW, h: BODY_H, fill: { color: 'F2F2F2' }, line: { color: 'D9D9D9', width: 1 } });
    slide.addText('No picture', { x: MARGIN, y: BODY_TOP + BODY_H / 2 - 0.15, w: picW, h: 0.3, align: 'center', fontSize: 12, color: GREY, fontFace: FONT });
  }
  const x = MARGIN + picW + 0.35;
  const w = W - x - MARGIN;
  const when = s.atS === undefined ? '' : `T+${formatClock(s.atS)}`;
  slide.addText([when, s.subtitle].filter(Boolean).join('   ·   '), {
    x, y: BODY_TOP, w, h: 0.3, bold: true, fontSize: 12, color: NAVY, fontFace: FONT, charSpacing: 1,
  });
  if (s.caption) {
    slide.addText(s.caption, { x, y: BODY_TOP + 0.4, w, h: BODY_H - 0.4, fontSize: 14, color: TEXT, fontFace: FONT, lineSpacingMultiple: 1.25, shrinkText: true, valign: 'top' });
  }
}

/**
 * How many slides the deck will have. The splitting rule for long lists lives here, so a caller can know the length
 * without reaching into pptxgenjs.
 */
export function briefSlideCount(brief: Brief): number {
  return brief.slides.reduce((n, s) => n + (s.kind === 'bullets' ? Math.max(1, Math.ceil((s.bullets ?? []).length / MAX_BULLETS)) : 1), 0);
}

/**
 * Pictures as data, not as addresses. PowerPoint has to carry the bytes, and a picture that cannot be fetched — a moved
 * asset, no network — must cost its own slide its picture rather than the whole file. Anything already inline is left be.
 */
export async function withEmbeddedImages(brief: Brief): Promise<Brief> {
  const seen = new Map<string, string | undefined>();
  const embed = async (url: string): Promise<string | undefined> => {
    if (url.startsWith('data:')) return url;
    const had = seen.get(url);
    if (seen.has(url)) return had;
    let out: string | undefined;
    try {
      const blob = await (await fetch(url)).blob();
      out = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error ?? new Error('could not read the picture'));
        reader.readAsDataURL(blob);
      });
    } catch {
      out = undefined;
    }
    seen.set(url, out);
    return out;
  };
  const slides = await Promise.all(brief.slides.map(async (s) => (s.image ? { ...s, image: await embed(s.image) } : s)));
  return { ...brief, slides };
}

/** Build the deck. Returns the configured pptxgenjs instance so callers can choose how to write it. */
export function briefDeck(brief: Brief): PptxGenJS {
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_16x9';
  pptx.title = brief.name;
  pptx.subject = 'Exercise storyboard brief';

  let n = 0;
  const next = (): Slide => {
    const slide = pptx.addSlide();
    slide.background = { color: WHITE };
    frame(slide, brief, ++n);
    return slide;
  };

  for (const s of brief.slides) {
    if (s.kind === 'title') {
      titleSlide(next(), s);
      continue;
    }
    if (s.kind === 'moment') {
      momentSlide(next(), s);
      continue;
    }
    if (s.kind === 'table' || s.kind === 'outcome') {
      tableSlide(next(), s, s.kind === 'outcome' ? ['Result', 'Count'] : ['Item', 'Value']);
      continue;
    }
    // Bullets: a long list is carried over rather than squeezed.
    const bullets = s.bullets ?? [];
    for (let i = 0; i < Math.max(1, Math.ceil(bullets.length / MAX_BULLETS)); i++) {
      const part = bullets.slice(i * MAX_BULLETS, (i + 1) * MAX_BULLETS);
      bulletSlide(next(), i === 0 ? s.title : `${s.title} (cont.)`, i === 0 ? s.subtitle : undefined, part);
    }
  }
  return pptx;
}

/** The deck as a file the browser can save, with every picture carried inside it. */
export async function briefBlob(brief: Brief): Promise<Blob> {
  return (await briefDeck(await withEmbeddedImages(brief)).write({ outputType: 'blob' })) as Blob;
}
