import type { Brief, BriefSlide } from './brief';
import { formatClock } from './geo';

/**
 * The brief as a page of slides: the same deck `briefPptx.ts` writes, drawn in HTML so it can be opened, read and
 * printed without PowerPoint. Each slide is a 16:9 card on screen and a landscape page in print, so what comes out of
 * the printer is a slide, not a wall of text.
 */

const esc = (s: string): string => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

/** Bullets past this many continue on the next slide, the same rule the PowerPoint writer uses. */
const MAX_BULLETS = 12;

function frame(brief: Brief, n: number, total: number, body: string, extraClass = ''): string {
  return `<section class="slide${extraClass ? ` ${extraClass}` : ''}">
  <header class="mark">${esc(brief.classification)}</header>
  <div class="body">${body}</div>
  <footer class="foot"><span>${esc(brief.name)}</span><span class="mark-bottom">${esc(brief.classification)}</span><span>${n} / ${total}</span></footer>
</section>`;
}

const headingHtml = (title: string, subtitle?: string): string =>
  `<h2>${esc(title)}</h2>${subtitle ? `<p class="sub">${esc(subtitle)}</p>` : ''}`;

const rowsHtml = (rows: [string, string][], heads: [string, string]): string =>
  `<table><thead><tr><th>${esc(heads[0])}</th><th>${esc(heads[1])}</th></tr></thead><tbody>${rows
    .map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`)
    .join('')}</tbody></table>`;

function slideBodies(s: BriefSlide): string[] {
  if (s.kind === 'title') {
    return [
      `<div class="title-slide">
    <h1>${esc(s.title)}</h1>
    ${s.subtitle ? `<p class="sub">${esc(s.subtitle)}</p>` : ''}
    <dl>${(s.rows ?? []).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
  </div>`,
    ];
  }
  if (s.kind === 'table' || s.kind === 'outcome') {
    return [`${headingHtml(s.title, s.subtitle)}${rowsHtml(s.rows ?? [], s.kind === 'outcome' ? ['Result', 'Count'] : ['Item', 'Value'])}`];
  }
  if (s.kind === 'moment') {
    const when = s.atS === undefined ? '' : `T+${formatClock(s.atS)}`;
    const line = [when, s.subtitle].filter((x): x is string => !!x).map(esc).join('   ·   ');
    return [
      `${headingHtml(s.title)}
  <div class="moment">
    ${s.image ? `<img src="${esc(s.image)}" alt=""/>` : '<div class="noimg">No picture</div>'}
    <div class="words">
      ${line ? `<p class="when">${line}</p>` : ''}
      ${s.caption ? `<p class="caption">${esc(s.caption)}</p>` : ''}
    </div>
  </div>`,
    ];
  }
  const bullets = s.bullets ?? [];
  const pages = Math.max(1, Math.ceil(bullets.length / MAX_BULLETS));
  return Array.from({ length: pages }, (_, i) => {
    const part = bullets.slice(i * MAX_BULLETS, (i + 1) * MAX_BULLETS);
    return `${headingHtml(i === 0 ? s.title : `${s.title} (cont.)`, i === 0 ? s.subtitle : undefined)}<ul>${part.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>`;
  });
}

/** The whole brief as one self-contained HTML page. */
export function briefHtml(brief: Brief): string {
  const bodies = brief.slides.flatMap((s) => slideBodies(s).map((body) => ({ body, title: s.kind === 'title' })));
  const slides = bodies.map((b, i) => frame(brief, i + 1, bodies.length, b.body, b.title ? 'is-title' : '')).join('\n');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<title>${esc(brief.name)} — exercise brief</title>
<style>
  :root { --navy:#1f3864; --text:#202020; --grey:#595959; --rule:#d9d9d9; }
  * { box-sizing: border-box; }
  body { margin:0; padding:24px; background:#4a4a4a; font:16px/1.45 Arial, Helvetica, sans-serif; color:var(--text); }
  /* A slide is 13.333in x 7.5in: the same 16:9 as the PowerPoint. */
  .slide { position:relative; width:13.333in; height:7.5in; margin:0 auto 24px; padding:0.45in 0.55in 0.5in; background:#fff;
           box-shadow:0 6px 24px rgba(0,0,0,.45); display:flex; flex-direction:column; overflow:hidden; }
  .mark, .mark-bottom { font-weight:700; font-size:11pt; color:var(--navy); letter-spacing:.02em; text-align:center; }
  .mark { margin:0 0 .18in; }
  .body { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; }
  .foot { display:grid; grid-template-columns:1fr auto 1fr; align-items:end; gap:.2in; font-size:9pt; color:var(--grey); }
  .foot span:last-child { text-align:right; }
  h1 { font-size:34pt; color:var(--navy); margin:0 0 .12in; text-align:center; }
  h2 { font-size:24pt; color:var(--navy); margin:0 0 .06in; padding-bottom:.07in; border-bottom:2px solid var(--navy); }
  .sub { margin:.06in 0 .14in; font-style:italic; color:var(--grey); font-size:12pt; }
  .is-title .body { justify-content:center; }
  .title-slide { text-align:center; }
  .title-slide .sub { font-style:normal; font-size:14pt; }
  .title-slide dl { display:grid; grid-template-columns:auto auto; gap:.06in .25in; justify-content:center; margin:.35in 0 0; font-size:12pt; }
  .title-slide dt { font-weight:700; color:var(--grey); text-align:right; }
  .title-slide dd { margin:0; text-align:left; }
  ul { margin:.1in 0 0; padding-left:.3in; font-size:14pt; }
  li { margin:0 0 .09in; }
  table { width:100%; border-collapse:collapse; margin-top:.12in; font-size:12pt; }
  th, td { border:1px solid var(--rule); padding:.07in .12in; text-align:left; vertical-align:top; }
  thead th { background:var(--navy); color:#fff; }
  tbody th { width:3.3in; background:#f6f7fa; }
  .moment { display:grid; grid-template-columns:55% 1fr; gap:.3in; flex:1 1 auto; min-height:0; margin-top:.12in; }
  .moment img { width:100%; height:100%; object-fit:contain; background:#f2f2f2; }
  .noimg { display:flex; align-items:center; justify-content:center; background:#f2f2f2; border:1px solid var(--rule); color:var(--grey); font-size:12pt; }
  .words { min-width:0; }
  .when { font-weight:700; color:var(--navy); font-size:12pt; letter-spacing:.06em; margin:0 0 .12in; }
  .caption { font-size:14pt; margin:0; }
  @page { size: 13.333in 7.5in; margin: 0; }
  @media print {
    body { background:#fff; padding:0; }
    .slide { margin:0; box-shadow:none; page-break-after:always; break-after:page; }
    .slide:last-child { page-break-after:auto; break-after:auto; }
  }
</style></head><body>
${slides}
</body></html>`;
}
