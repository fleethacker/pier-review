// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Dashboard } from './Dashboard';
import { ControllerContext } from './context';
import { setUnitSystem } from '../units';

afterEach(() => { cleanup(); setUnitSystem('navy'); });
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

it('separates backend working-load gust and application advisory from unavailable ultimate capacity', () => {
  setup(null, null, { envelope: { ...limits, assumptions: ['Fixture basis: 1-minute sustained at 10 m.'],
    result: { ...limits.result, worst: { wind_rel_deg: 90, limit_wind_kt: 40, limit_gust_kt: 50,
      advisory_gust_kt: 40, first_failure_element: 'line-1', failure_mode: 'WLL', outcome: 'limit_found' } } } });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  expect(screen.getByText('Corresponding working-limit gust').nextElementSibling?.textContent).toBe('50.0 kt');
  expect(screen.getByText('Application gust advisory').nextElementSibling?.textContent).toBe('40.0 kt');
  expect(screen.getByText('Ultimate-load / breaking gust: unavailable')).toBeTruthy();
  expect(screen.getByText(/not 80% line utilization/)).toBeTruthy();
  expect(screen.getByText(/Fixture basis: 1-minute sustained at 10 m/)).toBeTruthy();
  expect(screen.getByText(/wind FROM relative to the bow, clockwise/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'limits-fixture' })).toBeTruthy();
});

it.each([null, undefined])('does not derive a missing (%s) gust limit from current wind or a design factor', (gust) => {
  setup(null, null, { env: wind, envelope: { ...limits, result: { ...limits.result,
    worst: { wind_rel_deg: 90, limit_wind_kt: 40, limit_gust_kt: gust, advisory_gust_kt: gust,
      first_failure_element: 'line-1', failure_mode: 'WLL' } } } });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  expect(screen.getByText('Corresponding working-limit gust').nextElementSibling?.textContent).toBe('Unavailable');
  expect(screen.getByText('Application gust advisory').nextElementSibling?.textContent).toBe('Unavailable');
  expect(screen.getByText(/Averaging time and reference-height basis were not supplied/)).toBeTruthy();
});

it('preserves reported zero-wind failure instead of treating zero as absent', () => {
  setup(null, null, { envelope: { ...limits, result: { ...limits.result,
    worst: { wind_rel_deg: 90, limit_wind_kt: 0, limit_gust_kt: 0, advisory_gust_kt: 0,
      first_failure_element: 'line-1', failure_mode: 'WLL', outcome: 'fails_at_zero_wind' } } } });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  expect(screen.getByText('Sustained wind limit').nextElementSibling?.textContent).toBe('0.0 kt');
  expect(screen.getByText('Corresponding working-limit gust').nextElementSibling?.textContent).toBe('0.0 kt');
  expect(screen.getByText(/Fails with no wind; other assessed loads remain/)).toBeTruthy();
});

it.each([
  ['no_failure_in_range', /No limit established through 100 kt.*unknown/],
  ['undetermined', /Indeterminate solve at 25 kt/],
  ['invalid_inputs', /Invalid inputs; no usable limit/],
])('explains the %s search outcome without making up a capacity', (outcome, message) => {
  setup(null, null, { envelope: { ...limits, result: { ...limits.result,
    worst: { wind_rel_deg: 90, limit_wind_kt: null, first_failure_element: null, failure_mode: 'none', outcome,
      search_max_kt: 100, undetermined_at_kt: 25 } } } });
  fireEvent.click(screen.getByRole('tab', { name: /wind limits/i }));
  expect(screen.getByText(message)).toBeTruthy();
  expect(screen.getByText('Sustained wind limit').nextElementSibling?.textContent).toBe('Unavailable');
});

it('does not display zero MBS exceedance when the result contains no line MBS samples', () => {
  setup(result);
  fireEvent.click(screen.getByRole('tab', { name: /gust risk/i }));
  expect(screen.getByText(/Sampled line strength.*unavailable; no line MBS samples/)).toBeTruthy();
  expect(screen.getByText('Ultimate-load / breaking gust: unavailable')).toBeTruthy();
});

it('labels available MBS sample statistics separately from an ultimate gust threshold', () => {
  setup({ ...result, result: { ...result.result, p_any_exceeds_mbs: 0.1,
    elements: [{ ...result.result.elements[0], element_id: 'line-1', p_exceed_mbs: 0.1 }] } });
  fireEvent.click(screen.getByRole('tab', { name: /gust risk/i }));
  expect(screen.getByText(/Sampled line strength \(MBS\) exceedance: 10.0%/)).toBeTruthy();
  expect(screen.getByText(/sampled MBS exceedance does not predict line rupture/)).toBeTruthy();
});

it('uses metric lengths with knots for the current environment when metric display is selected', () => {
  setUnitSystem('metric');
  setup(null, null, { env: { ...wind, water_level_mllw_ft: 10 } });
  expect(screen.getByText('Water level').nextElementSibling?.textContent).toBe('3.0 m MLLW');
  expect(screen.getByText('Wind').nextElementSibling?.textContent).toBe('10 kt from 90°');
});
