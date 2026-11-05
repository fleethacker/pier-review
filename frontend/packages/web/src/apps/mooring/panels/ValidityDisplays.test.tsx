// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ControllerContext } from './context';
import { DataKey } from './DataKey';
import { ResultPanel } from './ResultPanel';
import { Overlay } from './Overlay';
afterEach(cleanup);

it.each(['invalid', 'unknown', undefined, 'valid', 'limited'])('analysis summaries respect %s validity', (validity) => {
  const state = { env: { wind_speed_kt: 5, wind_gust_kt: 7, wind_from_true_deg: 90, current_speed_kt: 0.2,
    current_set_true_deg: 180, water_level_mllw_ft: 0, source: 'mock' }, berth: null, side: 'starboard', tugAssignments: [],
    lines: [{ line_number: 1, parts: 1 }], analysis: { state: 'ok', response: { status: 'RED', backend: 'real',
      validity: validity ? { state: validity, reasons: [] } : undefined,
      result: { lines: [{ line_number: 1, pct_wll: 12, status: 'GREEN' }], findings: [],
        min_margin: { element_id: 'fender-1', pct_wll: 12 }, offset: { sway_ft: 1.2, surge_ft: 3.4 } } } } };
  render(<ControllerContext.Provider value={{ state: { use: (sel: (s: typeof state) => unknown) => sel(state) }, host: { store: {} } } as never}>
    <ResultPanel /><DataKey />
  </ControllerContext.Provider>);
  if (validity === 'valid' || validity === 'limited') {
    expect(screen.getByText('12%')).toBeTruthy();
    expect(screen.getByText('fender-1 · 12% WLL')).toBeTruthy();
  } else {
    expect(screen.queryByText('12%')).toBeNull();
    expect(screen.queryByText('fender-1 · 12% WLL')).toBeNull();
    expect(screen.queryByText(/1.2 ft sway/)).toBeNull();
    expect(screen.getAllByText('Unavailable').length).toBe(2);
  }
});

it.each(['invalid', 'unknown', undefined, 'valid', 'limited'])('sheet margins respect %s validity', (validity) => {
  const state = { overlay: { kind: 'sheet', id: 'S' } };
  const agent = { sheet: { state: 'ready', image: null, html: '<p>Fixture sheet</p>', error: null,
    sheet: { sheet_id: 'S', version: 1, status: 'RED', sources: [], warnings: [], rationale: [], approvals: [],
      validity: validity ? { state: validity } : undefined,
      line_plan: [{ line_number: 1, role: 'bow', pct_wll: 12, status: 'GREEN' }] } } };
  render(<ControllerContext.Provider value={{ state: { use: (sel: (s: typeof state) => unknown) => sel(state) },
    agent: { state: { use: (sel: (s: typeof agent) => unknown) => sel(agent) } } } as never}><Overlay /></ControllerContext.Provider>);
  if (validity === 'valid' || validity === 'limited') expect(screen.getByText(/12% of WLL/)).toBeTruthy();
  else {
    expect(screen.queryByText(/12% of WLL/)).toBeNull();
    expect(screen.getByText('Unavailable')).toBeTruthy();
  }
});
