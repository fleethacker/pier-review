import type { AgentSchemas } from '../types';

export type IntakeReport = AgentSchemas['IntakeReport'];
export type ConcernWindow = AgentSchemas['ConcernWindow'];
export type DataQualityIssue = AgentSchemas['DataQualityIssue'];

const RANK = { INFO: 0, AMBER: 1, RED: 2 } as const;
type Severity = keyof typeof RANK;

/** Worst severity among windows and data-quality issues, for the headline chip. */
export function worstSeverity(report: Pick<IntakeReport, 'windows' | 'data_quality'>): Severity {
  const all = [...report.windows.map((w) => w.severity), ...report.data_quality.map((d) => d.severity)] as Severity[];
  return all.reduce<Severity>((worst, s) => (RANK[s] > RANK[worst] ? s : worst), 'INFO');
}

/** "14:00-16:30Z" style span; falls back to the raw text when a time cannot be parsed. */
export function formatSpan(startUtc: string, endUtc: string): string {
  const fmt = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
  };
  return `${fmt(startUtc)} to ${fmt(endUtc)} UTC`;
}

/** Where the written summary came from, in words. The service names a provider only when a model wrote it. */
export function summaryProvenance(report: Pick<IntakeReport, 'summary_source' | 'narration_note'>): string {
  if (report.summary_source === 'llm') return 'Narrated by a language model; the numbers come from the stored results.';
  return `Deterministic summary${report.narration_note ? ` (${report.narration_note})` : ''}.`;
}

export function dataQualityLine(issue: DataQualityIssue): string {
  return `${issue.station_id}: ${issue.issue}. ${issue.detail}`;
}
