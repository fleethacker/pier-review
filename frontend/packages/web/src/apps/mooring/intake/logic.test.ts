import { describe, expect, it } from 'vitest';
import { dataQualityLine, formatSpan, summaryProvenance, worstSeverity } from './logic';
import type { ConcernWindow, DataQualityIssue } from './logic';

const win = (severity: ConcernWindow['severity']) => ({ severity }) as ConcernWindow;
const dq = (severity: DataQualityIssue['severity']) => ({ severity }) as DataQualityIssue;

describe('intake helpers', () => {
  it('finds the worst severity across windows and data issues', () => {
    expect(worstSeverity({ windows: [], data_quality: [] })).toBe('INFO');
    expect(worstSeverity({ windows: [win('AMBER')], data_quality: [dq('INFO')] })).toBe('AMBER');
    expect(worstSeverity({ windows: [win('INFO')], data_quality: [dq('RED')] })).toBe('RED');
  });
  it('formats a UTC span and survives bad times', () => {
    expect(formatSpan('2026-11-05T14:00:00Z', '2026-11-05T16:30:00Z')).toBe('14:00 to 16:30 UTC');
    expect(formatSpan('soon', 'later')).toBe('soon to later UTC');
  });
  it('says where the summary came from', () => {
    expect(summaryProvenance({ summary_source: null, narration_note: 'provider not configured' })).toBe('Deterministic summary (provider not configured).');
    expect(summaryProvenance({ summary_source: 'deterministic', narration_note: null })).toBe('Deterministic summary.');
    expect(summaryProvenance({ summary_source: 'llm', narration_note: null })).toMatch(/language model/);
  });
  it('writes a data-quality line', () => {
    expect(dataQualityLine({ station_id: 'S1', issue: 'mock', severity: 'INFO', detail: 'Synthetic.' })).toBe('S1: mock. Synthetic.');
  });
});
