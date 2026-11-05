// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Dashboard } from './Dashboard';
import { ControllerContext } from './context';

afterEach(cleanup);
function setup(exceedance: unknown = null, timeline: unknown = null) {
  const state = { alerts: [], env: null, envMode: { kind: 'manual' }, windHistory: [], lines: [],
    risk: { running: null, error: null, exceedance, timeline, envelope: null } };
  render(<ControllerContext.Provider value={{ state: { use: (sel: (s: typeof state) => unknown) => sel(state) } } as never}>
    <Dashboard />
  </ControllerContext.Provider>);
}
const result = { result_id: 'risk-fixture', status: 'AMBER', backend: 'real', validity: { state: 'limited', reasons: [] },
  result: { n_samples: 10, n_valid: 10, n_failed: 0, p_any_exceeds_wll: 0, p_any_exceeds_mbs: 0,
    governing_element: 'fixture-fender', pointwise_only: true, uncertainty_model: { qualification: 'unqualified' },
    elements: [{ element_id: 'fixture-fender', p_exceed_wll: 0, p_exceed_mbs: null, tension_p50_lbf: 500, tension_p95_lbf: 600 }] } };

it.each(['invalid', 'unknown', undefined])('withholds probability numbers for %s validity', (validity) => {
  setup({ ...result, validity: validity ? { state: validity, reasons: [] } : undefined });
  fireEvent.click(screen.getByRole('tab', { name: /gust risk/i }));
  expect(screen.getByText(/probability unavailable/i)).toBeTruthy();
  expect(screen.queryByText(/0\.0%/)).toBeNull();
});
it('withholds a legacy zero scalar when no samples succeeded', () => {
  setup({ ...result, result: { ...result.result, n_valid: 0, n_failed: 10 } });
  fireEvent.click(screen.getByRole('tab', { name: /gust risk/i }));
  expect(screen.getByText(/probability unavailable/i)).toBeTruthy();
  expect(screen.queryByText(/0\.0%/)).toBeNull();
});
it('labels usable zero scenario statistics and does not turn absent fender MBS into zero', () => {
  setup(result);
  fireEvent.click(screen.getByRole('tab', { name: /gust risk/i }));
  expect(screen.getByText(/any modeled element.*0\.0%/i)).toBeTruthy();
  expect(screen.getByText(/not an operational risk estimate/i)).toBeTruthy();
  expect(screen.getByText(/instantaneous samples/i)).toBeTruthy();
  const row = screen.getByText('fixture-fender').closest('tr')!;
  expect(row.children[2].textContent).toBe('n/a');
  expect(screen.getByText('Force p50')).toBeTruthy();
});
it('labels the generated timeline as synthetic rather than a public forecast', () => {
  setup(null, { result_id: 'timeline-fixture', status: 'AMBER', backend: 'real', validity: { state: 'limited' },
    result: { steps: [], first_amber_utc: null, first_red_utc: null, forcing_source: 'synthetic_training' } });
  fireEvent.click(screen.getByRole('tab', { name: /forecast|timeline/i }));
  expect(screen.getByText(/synthetic training timeline.*not a weather forecast/i)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Run 24 h forecast' })).toBeNull();
});
