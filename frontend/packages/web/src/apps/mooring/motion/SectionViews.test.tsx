// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MotionController } from './controller';
import type { MotionState } from './controller';
import { adaptFrame } from './frames';
import type { SimFrame } from './frames';
import { SectionViews } from './SectionViews';
import type { SectionView } from './SectionViews';
import { loading, workspace } from './workspace.test-fixtures';

const raw = JSON.parse(readFileSync(path.resolve(__dirname, '../../../../../../../contract/examples/modeling/sim_frame.json'), 'utf8')) as SimFrame;
afterEach(cleanup);
function state(type = 'DDG'): MotionState {
  const controller = new MotionController({ faceBearingDeg: () => 90, tugIds: () => [], lineNumbers: () => [], layoutKey: () => 'section-test', ensureScenario: async () => null, initialState: () => null });
  const frame = adaptFrame({ ...raw, loading }, { faceBearingDeg: 90 });
  return { ...controller.s, workspace: { ...workspace, ship: { ...workspace.ship, hull_type: type } }, frame: { ...frame, ship: { ...frame.ship, rollDeg: 0, pitchDeg: 0 } } };
}
function coordinates(element: Element | null): number[][] {
  expect(element).toBeTruthy();
  return element!.getAttribute('points')!.split(' ').map(pair => pair.split(',').map(Number));
}
function change(s: MotionState, values: Partial<typeof loading>, pose: { rollDeg?: number | null; pitchDeg?: number | null } = {}): MotionState {
  return { ...s, frame: { ...s.frame!, loading: { ...s.frame!.loading!, ...values }, ship: { ...s.frame!.ship, ...pose } } };
}

describe('Vessel section illustrations', () => {
  it.each(['side', 'forward', 'aft'] as const)('renders distinct DDG, CG, LHD and CVN silhouettes in the %s view', view => {
    const silhouettes = new Set<string>();
    for (const type of ['DDG', 'CG', 'LHD', 'CVN']) {
      const { container, unmount } = render(<SectionViews s={state(type)} view={view} />);
      const parts = [...container.querySelectorAll('[data-vessel-part]')];
      expect(parts.length).toBeGreaterThan(6);
      silhouettes.add(parts.map(part => part.getAttribute('points')).join('|'));
      expect(container.querySelector('[data-modeled-draft]')).toBeTruthy();
      expect(screen.getByText(/Illustrative profile/)).toBeTruthy();
      unmount();
    }
    expect(silhouettes.size).toBe(4);
  });

  it.each(['side', 'forward', 'aft'] as const)('preserves the same horizontal and vertical scale in %s', view => {
    const s = state();
    const { container } = render(<SectionViews s={s} view={view} compact />);
    const deck = coordinates(container.querySelector('[data-vessel-part="main-deck"]'));
    const keel = coordinates(container.querySelector('[data-modeled-draft]'));
    const horizontalFeet = view === 'side' ? workspace.ship.loa_ft : workspace.ship.beam_ft;
    expect((deck[2][0] - deck[1][0]) / (keel[0][1] - 205)).toBeCloseTo(horizontalFeet / loading.draft_aft_ft);
  });

  it('does not draw a water surface or submerged color when the water level is unavailable', () => {
    const s = state();
    s.frame = { ...s.frame!, environment: { ...s.frame!.environment!, water: { ...s.frame!.environment!.water, available: false, levelMllwFt: null } } };
    const { container } = render(<SectionViews s={s} view="side" />);
    expect(container.querySelector('[data-section-waterline]')).toBeNull();
    expect(container.querySelector('[clip-path]')).toBeNull();
    expect(screen.getByText(/Water level unavailable · section referenced to modeled draft/)).toBeTruthy();
  });

  it.each(['forward', 'aft'] as const)('puts the carrier island on the labelled starboard side in the %s view', view => {
    const { container } = render(<SectionViews s={state('CVN')} view={view} />);
    const island = coordinates(container.querySelector('[data-vessel-part="superstructure-3"]'));
    const starboard = Number(screen.getByText('STARBOARD').getAttribute('x'));
    expect(island.every(([x]) => (x - 450) * (starboard - 450) > 0)).toBe(true);
  });

  it.each(['forward', 'aft'] as const)('projects port cargo and heel consistently in the %s view', view => {
    const s = change(state(), { payloads: [{ payload_id: 'port', label: 'Port cargo', weight_lbf: 100, x_ft: 0, y_ft: 10, z_ft: 0 }] });
    const { container, rerender } = render(<SectionViews s={s} view={view} />);
    const point = () => container.querySelector('[data-section-payload="port"] rect')!;
    const baselineY = Number(point().getAttribute('y'));
    const portLabelX = Number(screen.getByText('PORT').getAttribute('x'));
    expect((Number(point().getAttribute('x')) + 6 - 450) * (portLabelX - 450)).toBeGreaterThan(0);
    rerender(<SectionViews s={change(s, { roll_deg: -3 }, { rollDeg: -3 })} view={view} />);
    expect(Number(point().getAttribute('y'))).toBeGreaterThan(baselineY); // Port-down heel stays down from either end.
  });

  it('uses each backend end draft once while deck and cargo follow pitch', () => {
    const s = change(state(), { draft_fwd_ft: 24, draft_aft_ft: 16, payloads: [{ payload_id: 'bow', label: 'Bow cargo', weight_lbf: 100, x_ft: 100, y_ft: 0, z_ft: 25 }] });
    const { container, rerender } = render(<SectionViews s={s} view="side" />);
    const keel = () => coordinates(container.querySelector('[data-modeled-draft]'));
    const baselineKeel = keel();
    const deck = container.querySelector('[data-vessel-part="main-deck"]')!.getAttribute('points');
    const payload = () => Number(container.querySelector('[data-section-payload="bow"] rect')!.getAttribute('y'));
    const baselinePayload = payload();
    expect((baselineKeel[1][1] - 205) / (baselineKeel[0][1] - 205)).toBeCloseTo(24 / 16);
    rerender(<SectionViews s={change(s, { pitch_deg: 2 }, { pitchDeg: 2 })} view="side" />);
    expect(keel()).toEqual(baselineKeel); // The given drafts already include trim.
    expect(container.querySelector('[data-vessel-part="main-deck"]')!.getAttribute('points')).not.toBe(deck);
    expect(payload()).toBeGreaterThan(baselinePayload);
  });

  it.each(['side', 'forward', 'aft'] as const)('sinks deck, CG and payload together while the waterline stays fixed in %s', view => {
    const s = change(state(), { payloads: [{ payload_id: 'cargo', label: 'Cargo', weight_lbf: 100, x_ft: 0, y_ft: 0, z_ft: 25 }] });
    const { container, rerender } = render(<SectionViews s={s} view={view} />);
    const deckY = () => coordinates(container.querySelector('[data-vessel-part="main-deck"]'))[0][1];
    const cgY = () => Number(container.querySelector('[data-section-cg] circle')!.getAttribute('cy'));
    const cargoY = () => Number(container.querySelector('[data-section-payload] rect')!.getAttribute('y'));
    const before = [deckY(), cgY(), cargoY()];
    rerender(<SectionViews s={change(s, { sinkage_ft: 2, mean_draft_ft: 22, draft_fwd_ft: 22, draft_aft_ft: 22, maximum_draft_ft: 22 })} view={view} />);
    const deltas = [deckY(), cgY(), cargoY()].map((n, i) => n - before[i]);
    expect(deltas[0]).toBeGreaterThan(0);
    expect(deltas[1]).toBeCloseTo(deltas[0]);
    expect(deltas[2]).toBeCloseTo(deltas[0]);
    expect(container.querySelector('[data-section-waterline]')!.getAttribute('y1')).toBe('205');
  });

  it.each([false, true])('keeps unknown seabed and attitude unavailable (compact=%s)', compact => {
    const { container } = render(<SectionViews s={change(state(), {}, { rollDeg: null, pitchDeg: null })} view="side" compact={compact} />);
    expect(container.querySelector('[data-section-seabed]')).toBeNull();
    expect(screen.getByText(compact ? 'Depth unavailable' : /Local seabed \/ clearance unavailable/)).toBeTruthy();
    expect(screen.getAllByText('unavailable / unavailable')).toHaveLength(2);
    expect(screen.queryByText('0.00 ft / 0.00 ft')).toBeNull();
  });

  it.each([false, true])('preserves negative clearance and an invalid loading alert (compact=%s)', compact => {
    const s = change(state(), { local_depth_mllw_ft: 18, under_keel_ft: -1, under_keel_lower_ft: -1.5, validity: { state: 'invalid', reasons: [{ code: 'GROUNDING', message: 'Modeled keel intersects supplied seabed.' }] } });
    const { container } = render(<SectionViews s={s} view="side" compact={compact} />);
    expect(screen.getByText('-1.00 ft / -1.50 ft')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('intersects supplied seabed');
    expect(container.querySelector('[data-section-seabed]')).toBeTruthy();
    expect(container.querySelector('[data-section-vessel]')).toBeNull();
  });

  it('supports three independent compact views without external map state or shared SVG ids', () => {
    const s = state();
    const { container } = render(<>{(['forward', 'aft', 'side'] as SectionView[]).map(view => <SectionViews key={view} s={s} view={view} compact />)}</>);
    expect(screen.getAllByRole('img')).toHaveLength(3);
    expect(new Set([...container.querySelectorAll('clipPath')].map(clip => clip.id)).size).toBe(3);
    for (const svg of container.querySelectorAll('svg')) expect(svg.closest('[hidden], [aria-hidden="true"]')).toBeNull();
  });
});
