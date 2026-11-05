import { formatClock } from './geo';
import { compareResults } from './montecarlo';
import type { McResult } from './montecarlo';
import type { RedTeamSpec, ScenarioConfig } from './types';

const csvCell = (v: string | number | undefined): string => {
  const t = v === undefined ? '' : String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};

/** One row per outcome per sweep value: the chances, with their intervals. Opens in any spreadsheet. */
export function resultCsv(result: McResult): string {
  const rows = [['group', 'outcome', 'runs_with_outcome', 'runs', 'probability', 'ci95_low', 'ci95_high', 'half_width', 'mean_time_s']];
  for (const g of result.groups) {
    for (const o of g.outcomes) {
      rows.push([g.label, o.label, o.hits, o.n, o.p.toFixed(5), o.lo.toFixed(5), o.hi.toFixed(5), o.halfWidth.toFixed(5), o.meanTimeS === null ? '' : o.meanTimeS.toFixed(1)].map(String));
    }
  }
  return rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';
}

/** Everything needed to reproduce and read the batch: the scenario, the settings and the results. */
export function resultJson(base: ScenarioConfig, spec: RedTeamSpec, result: McResult): string {
  return JSON.stringify({ exportedAt: new Date().toISOString(), scenario: { ...base, redTeam: undefined }, redTeam: spec, result }, null, 2);
}

const esc = (t: string) => t.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const pct = (p: number, d = 1) => `${(p * 100).toFixed(d)}%`;

/** A self-contained page that prints well (use the browser's Save as PDF). */
export function reportHtml(base: ScenarioConfig, spec: RedTeamSpec, result: McResult, baseline?: McResult | null): string {
  const deltas = baseline ? compareResults(baseline, result) : [];
  const groups = result.groups
    .map((g, gi) => {
      const rows = g.outcomes
        .map((o) => {
          const d = deltas.find((x) => x.label === g.label)?.rows.find((r) => r.id === o.id);
          const delta = d ? `<td>${d.delta >= 0 ? '+' : ''}${(d.delta * 100).toFixed(1)} pts${d.significant ? ' (significant)' : ''}</td>` : baseline ? '<td></td>' : '';
          return `<tr><td>${esc(o.label)}</td><td>${o.hits} / ${o.n}</td><td><b>${pct(o.p)}</b></td><td>${pct(o.lo)} to ${pct(o.hi)}</td><td>${o.meanTimeS === null ? '' : `T+${formatClock(o.meanTimeS)}`}</td>${delta}</tr>`;
        })
        .join('');
      const sens = g.sensitivity
        .filter((r) => Math.abs(r.corr) >= 0.1)
        .sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr))
        .slice(0, 8)
        .map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(g.outcomes.find((o) => o.id === r.outcomeId)?.label ?? r.outcomeId)}</td><td>${r.corr.toFixed(2)}</td></tr>`)
        .join('');
      return `<h2>${spec.sweep ? esc(g.label) : 'Results'} <small>${g.runs} runs</small></h2>
<table><thead><tr><th>Outcome</th><th>Runs</th><th>Chance</th><th>95% interval</th><th>Typical time</th>${baseline ? '<th>Change vs baseline</th>' : ''}</tr></thead><tbody>${rows}</tbody></table>
${sens ? `<h3>What drives it</h3><table><thead><tr><th>Variation</th><th>Outcome</th><th>Correlation</th></tr></thead><tbody>${sens}</tbody></table>` : ''}
${gi < result.groups.length - 1 ? '<hr/>' : ''}`;
    })
    .join('');
  const varied = spec.perturbations.map((p) => `<li>${esc(p.label ?? p.id)}</li>`).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/><title>Red team report: ${esc(base.name)}</title>
<style>body{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#111}table{border-collapse:collapse;width:100%;margin:.5rem 0 1.25rem}th,td{border:1px solid #bbb;padding:.3rem .5rem;text-align:left}th{background:#eee}small{color:#666;font-weight:400}@media print{body{margin:0}}</style></head><body>
<h1>Red team report</h1>
<p><b>${esc(base.name)}</b>${base.description ? ` &mdash; ${esc(base.description)}` : ''}<br/>
${result.totalRuns.toLocaleString('en-US')} runs in ${(result.elapsedMs / 1000).toFixed(1)} s${result.stopped ? ' (stopped early)' : ''}${result.converged ? ' (stopped when every chance reached the target precision)' : ''}. Seed ${spec.seed}. Scenario duration ${formatClock(base.durationS)}.</p>
${varied ? `<p>Varied from run to run:</p><ul>${varied}</ul>` : '<p>Only the chance rolls varied from run to run.</p>'}
${groups}
<p><small>Chances are measured on a simplified model with illustrative parameters. They show how outcomes respond to changes, not what would happen in practice. Exported ${new Date().toISOString()}.</small></p>
</body></html>`;
}

/** Hand text to the browser as a file download. */
export function downloadText(filename: string, mime: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const fileSafe = (name: string): string => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'scenario';

/** Open the report in a new tab, ready to print. Returns false if the browser blocked the window. */
export function openReport(html: string): boolean {
  const w = window.open('', '_blank');
  if (!w) return false;
  w.document.open();
  w.document.write(html);
  w.document.close();
  return true;
}
