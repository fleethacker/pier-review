// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Dashboard } from './Dashboard';
import { ControllerContext } from './context';

afterEach(cleanup);
function setup(exceedance: unknown = null, timeline: unknown = null, options: { env?: unknown; envelope?: unknown } = {}) {
  const state = { alerts: [], env: options.env ?? null, envMode: { kind: 'manual' }, windHistory: [], lines: [],
    risk: { running: null, error: null, exceedance, timeline, envelope: options.envelope ?? null } };
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

const wind = { wind_speed_kt: 10, wind_gust_kt: 20, wind_from_true_deg: 90, current_speed_kt: 0,
  current_set_true_deg: 0, water_level_mllw_ft: 0 };
const limits = { result_id: 'limits-fixture', status: 'AMBER', backend: 'real', validity: { state: 'limited' },
  result: { points: [0, 90, 180, 270].map((wind_rel_deg) => ({ wind_rel_deg, limit_wind_kt: 40 })), worst: null } };

it('compares sustained wind with sustained-wind limits', () => {
  setup(null, null, { env: wind, envelope: limits });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  const plot = screen.getByRole('img', { name: 'Limiting wind speed by wind angle' });
  const ring = plot.querySelector('circle[stroke-dasharray]')!;
  expect(Number(ring.getAttribute('r'))).toBeCloseTo(15); // 10 kt / (40 kt × 1.1) × 66 px.
  expect(screen.getByText(/current sustained wind/i)).toBeTruthy();
  expect(screen.queryByText(/inside.*plan holds/i)).toBeNull();
});

it.each(['invalid', 'unknown'])('withholds the limit plot for %s validity', (validity) => {
  setup(null, null, { env: wind, envelope: { ...limits, validity: { state: validity } } });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  expect(screen.queryByRole('img', { name: 'Limiting wind speed by wind angle' })).toBeNull();
  expect(screen.getByText(/wind limits unavailable/i)).toBeTruthy();
});
