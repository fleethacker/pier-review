// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SceneStore } from '../../../scene/store';
import { MooringController } from '../controller';
import type { ShipClass } from '../types';
import { ControllerContext } from './context';
import { SetupPanel } from './SetupPanel';
import { RecommendPanel } from './RecommendPanel';

let controller: MooringController;
afterEach(() => { cleanup(); controller?.dispose(); });

function setup(classId: string, fittings: unknown[] = [], selectedClassId = classId) {
  controller = new MooringController({ store: new SceneStore() });
  controller.state.set({
    shipClassId: selectedClassId, loading: 'full_load',
    ship: { class_id: classId, loading_conditions: [{ name: 'full_load' }], fittings,
      wind_area_lateral_ft2: 2000, wind_area_frontal_ft2: 400 } as ShipClass,
  });
  render(<ControllerContext.Provider value={controller}><SetupPanel /><RecommendPanel /></ControllerContext.Provider>);
}

it.each(['CG-47', 'LHD-1', 'CVN-68'])('explains the missing %s fittings and blocks recommendations', (id) => {
  setup(id);
  expect(screen.getByRole('button', { name: 'Recommend layouts' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByLabelText('Selected class capabilities').textContent).toContain('Present · unqualified');
  expect(screen.getByRole('status').textContent).toContain('No class-specific mooring fittings');
});

it('allows the demonstration workflow with actual fitting and loading records', () => {
  setup('CUSTOM', [{ fitting_id: 'CUSTOM-BITT' }]);
  expect(screen.getByRole('button', { name: 'Recommend layouts' }).hasAttribute('disabled')).toBe(false);
  expect(screen.getByLabelText('Selected class capabilities').textContent).toContain('Demonstration only');
});

it('blocks old ship actions during a class change', () => {
  setup('DDG-51-FIIA', [{}], 'CG-47');
  expect(screen.getByRole('button', { name: 'Recommend layouts' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('status').textContent).toContain('Waiting');
});
